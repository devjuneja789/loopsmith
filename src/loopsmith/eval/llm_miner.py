"""LLM-assisted mining: generalizes the heuristic miners.

The model sees a compact digest of imported traces plus the currently
active entries, and must answer with proposals in the same Proposal
schema. Every citation is validated against the database: a proposal
whose evidence does not resolve is dropped, so nothing enters the gate
ungrounded.
"""

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from loopsmith.core.models import Evidence, Proposal
from loopsmith.core.store import Store
from loopsmith.core.util import content_id, now_utc
from loopsmith.mining.heuristics import slugify
from loopsmith.traces import query as q

MAX_DIGEST_CHARS = 9000
MAX_PROPOSALS = 3
MAX_BODY_CHARS = 4000

SYSTEM_PROMPT = """You are a harness engineer. Read coding-session traces and propose
the smallest, evidence-backed edits to a coding agent's persistent harness:

- "instruction": project rules (e.g. the command that actually works)
- "memory": durable facts or quirks learned from failures
- "skill": reusable procedures

Rules:
- Only propose what the traces support; cite trace ids and event seq numbers.
- Prefer one precise entry over many vague ones.
- name: lowercase slug (a-z, 0-9, '-'), max 48 chars.
- body_md: <= 1200 chars of Markdown.
- Never duplicate an entry that is already active (listed below).

Reply with JSON only:
{"proposals": [{"op": "create", "kind": "instruction", "name": "use-x",
  "body_md": "# Use `x`\\n\\n...", "rationale": "...",
  "evidence": [{"trace_id": "t...", "event_refs": [3, 4],
                "pattern": "retry_loop", "excerpt": "..."}]}]}
If nothing is warranted, reply {"proposals": []}."""


class _EvidenceIn(BaseModel):
    trace_id: str
    event_refs: list[int] = Field(default_factory=list)
    pattern: str = "llm"
    excerpt: str = ""


class _ProposalIn(BaseModel):
    op: str = "create"
    kind: str
    name: str
    body_md: str
    rationale: str = ""
    evidence: list[_EvidenceIn] = Field(default_factory=list)


def _digest(store: Store) -> str:
    lines: list[str] = []
    for trace, events in store.all_events_by_trace():
        lines.append(
            f"## trace {trace.id} (project {trace.project}, agent {trace.session.agent})")
        for ev in events:
            lines.append(f"{ev.seq:>3} {ev.kind}: {q.summarize(ev)[:150]}")
    return "\n".join(lines)[:MAX_DIGEST_CHARS]


def _active_summary(store: Store) -> str:
    lines = []
    for entry in store.list_entries():
        active = store.active_version(entry.id)
        if active:
            lines.append(f"- {entry.kind}/{entry.name} (v{active.n})")
    return "\n".join(lines) or "(none)"


def _valid_evidence(store: Store, raw: list[_EvidenceIn]) -> list[Evidence]:
    evidence: list[Evidence] = []
    for item in raw:
        refs = [ref for ref in item.event_refs if store.event_exists(item.trace_id, ref)]
        if refs:
            evidence.append(Evidence(
                trace_id=item.trace_id, event_refs=refs,
                pattern=item.pattern or "llm", excerpt=item.excerpt[:160]))
    return evidence


def mine_with_llm(store: Store, client: Any, max_proposals: int = MAX_PROPOSALS) -> list[Proposal]:
    traces = store.list_traces()
    if not traces:
        return []
    user_prompt = (
        "# Imported traces\n\n" + _digest(store) +
        "\n\n# Already active\n\n" + _active_summary(store) +
        "\n\nPropose at most "
        f"{max_proposals} edits, JSON only."
    )
    result = client.chat(
        [{"role": "system", "content": SYSTEM_PROMPT},
         {"role": "user", "content": user_prompt}],
        temperature=0.2, max_tokens=1600,
    )
    from loopsmith.eval.llm import extract_json

    data = extract_json(result.text)
    raw_items = data.get("proposals")
    if not isinstance(raw_items, list):
        return []

    created: list[Proposal] = []
    for item in raw_items[:max_proposals]:
        try:
            parsed = _ProposalIn.model_validate(item)
        except ValidationError:
            continue
        if parsed.kind not in ("memory", "skill", "instruction"):
            continue
        name = slugify(parsed.name)[:48]
        body = parsed.body_md.strip()
        if not body or len(body) > MAX_BODY_CHARS:
            continue
        evidence = _valid_evidence(store, parsed.evidence)
        if not evidence:
            continue  # ungrounded proposals never enter the gate

        entry = store.get_entry(parsed.kind, name)
        if entry is None:
            op, target_n = "create", None
        else:
            active = store.active_version(entry.id)
            if active is None or active.body_md.strip() == body:
                continue
            op, target_n = "update", active.n

        pid = content_id("p", parsed.kind, name, op, body, "llm")
        if store.get_proposal(pid):
            continue
        proposal = Proposal(
            id=pid, op=op, kind=parsed.kind, name=name, target_n=target_n,
            body_md=body, rationale=(parsed.rationale or "LLM proposal")[:500],
            origin="llm", evidence=evidence[:12], created_at=now_utc(),
        )
        store.add_proposal(proposal)
        created.append(proposal)
    if created:
        store.log("mined_llm", {"new_proposals": len(created)})
    return created