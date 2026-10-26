"""Deterministic heuristic miners.

Each miner scans canonical trace events and returns Findings: the smallest
evidence-cited edits to harness state. Findings are merged by (kind, name),
converted to Proposals, and persisted. Proposal ids are content hashes, so
re-mining the same traces is a no-op -- the continual loop only proposes
something new when new evidence arrives.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from loopsmith.core.models import Evidence, Proposal
from loopsmith.core.store import Store
from loopsmith.core.util import content_id, now_utc
from loopsmith.traces import query as q
from loopsmith.traces.schema import Trace, TraceEvent

CORRECTION_CUES = (
    "no,", "no —", "don't", "do not", "instead", "wrong", "actually",
    "stop", "not raw", "use `",
)

MAX_EVIDENCE_PER_FINDING = 12


@dataclass
class Finding:
    kind: str            # "memory" | "skill" | "instruction"
    name: str
    body_md: str
    rationale: str
    evidence: list[Evidence] = field(default_factory=list)
    pattern: str = ""
    priority: int = 0    # higher = stronger signal; drives merge tie-breaks
    stats: dict[str, int] = field(default_factory=dict)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "unnamed"


def _trace_pair(store: Store, project: str | None) -> list[tuple[Trace, list[TraceEvent]]]:
    return store.all_events_by_trace(project=project)


# -- miner 1: command retry loops ------------------------------------------

def retry_loop_miner(traces: Iterable[tuple[Trace, list[TraceEvent]]]) -> list[Finding]:
    """Same command fails >= 2 consecutive times, then succeeds -> flaky memory."""
    findings: list[Finding] = []
    for trace, events in traces:
        pending: dict[str, list[TraceEvent]] = {}
        for ev in events:
            if ev.kind not in ("test.run", "tool.call", "tool.result"):
                continue
            cmd = q.command(ev).strip().lower()
            if not cmd:
                continue
            if q.ok(ev):
                fails = pending.get(cmd, [])
                if len(fails) >= 2:
                    findings.append(_flaky_finding(trace, cmd, fails, ev))
                pending[cmd] = []
            else:
                pending.setdefault(cmd, []).append(ev)
    return findings


def _flaky_finding(trace: Trace, cmd: str, fails: list[TraceEvent],
                   success: TraceEvent) -> Finding:
    if " -k " in cmd:
        test_id = slugify(cmd.split(" -k ", 1)[1].split()[0])
        name = f"flaky-{test_id}"
    else:
        name = f"flaky-{slugify(cmd)}"
    body = (
        f"# Flaky command: `{cmd}`\n\n"
        f"`{cmd}` failed {len(fails)} consecutive times before succeeding in the "
        f"same session (project: {trace.project}). Treat a single failure as "
        "transient: rerun the command once before investigating.\n"
    )
    excerpt = f"{cmd} -> exit {fails[0].payload.get('exit_code', 1)} (x{len(fails)}) then exit 0"
    return Finding(
        kind="memory", name=name, body_md=body,
        rationale=(f"Retry loop in trace {trace.id}: {len(fails)} consecutive "
                   f"failures of `{cmd}` followed by success."),
        evidence=[Evidence(
            trace_id=trace.id,
            event_refs=[f.seq for f in fails] + [success.seq],
            pattern="command_retry_loop", excerpt=excerpt,
        )],
        pattern="command_retry_loop", priority=5 + len(fails),
        stats={"retry_loops": 1},
    )


# -- miner 2: user corrections ----------------------------------------------

def user_correction_miner(traces: Iterable[tuple[Trace, list[TraceEvent]]]) -> list[Finding]:
    """A corrective user message followed by compliance -> instruction."""
    findings: list[Finding] = []
    for trace, events in traces:
        evs = list(events)
        for i, ev in enumerate(evs):
            if ev.kind != "user.message":
                continue
            text = q.text(ev)
            if not text or len(text) > 600:
                continue
            low = text.lower()
            if not any(cue in low for cue in CORRECTION_CUES):
                continue
            cmd = _first_code_span(text)
            if not cmd:
                continue
            window = evs[i + 1: i + 4]
            compliance = next(
                (e for e in window
                 if e.kind in ("tool.call", "test.run")
                 and cmd.split()[0].lower() in q.command(e).lower()),
                None,
            )
            if compliance is None:
                continue
            findings.append(_correction_finding(trace, ev, compliance, cmd, text))
    return findings


def _first_code_span(text: str) -> str | None:
    match = re.search(r"`([^`\n]{2,60})`", text)
    if not match:
        return None
    span = match.group(1).strip()
    return span if re.search(r"[a-zA-Z]", span) else None


def _correction_finding(trace: Trace, user: TraceEvent, compliance: TraceEvent,
                        cmd: str, text: str) -> Finding:
    name = f"use-{slugify(cmd)}"
    body = (
        f"# Use `{cmd}`\n\n"
        f"A user corrected the agent for using a different command; prefer "
        f"`{cmd}` in this project. The correction was followed by compliance "
        "in the same turn.\n\n"
        "## When\n\n"
        f"- Running or verifying tests in {trace.project}.\n"
    )
    return Finding(
        kind="instruction", name=name, body_md=body,
        rationale=(f"User correction in trace {trace.id} (events "
                   f"{user.seq}-{compliance.seq}), followed by compliance."),
        evidence=[Evidence(
            trace_id=trace.id, event_refs=[user.seq, compliance.seq],
            pattern="user_correction", excerpt=q.excerpt(text),
        )],
        pattern="user_correction", priority=20,
        stats={"corrections": 1},
    )


# -- miner 3: fail -> edit -> pass cycles -----------------------------------

def fix_then_verify_miner(traces: Iterable[tuple[Trace, list[TraceEvent]]]) -> list[Finding]:
    """Failing test, then a file edit, then a passing run -> verify skill."""
    cycles: list[tuple[Trace, TraceEvent, TraceEvent, TraceEvent]] = []
    for trace, events in traces:
        last_fail: TraceEvent | None = None
        edit_after_fail: TraceEvent | None = None
        for ev in events:
            if ev.kind == "test.run" and not q.ok(ev):
                last_fail, edit_after_fail = ev, None
            elif ev.kind == "file.edit" and last_fail is not None and edit_after_fail is None:
                edit_after_fail = ev
            elif (ev.kind == "test.run" and q.ok(ev)
                  and last_fail is not None and edit_after_fail is not None):
                cycles.append((trace, last_fail, edit_after_fail, ev))
                last_fail, edit_after_fail = None, None
    if not cycles:
        return []
    verify_counts = Counter(q.norm_command(q.command(pass_ev)) for _, _, _, pass_ev in cycles)
    top_cmd, _ = verify_counts.most_common(1)[0]
    trace_ids = {t.id for t, _, _, _ in cycles}
    body = (
        "# Verify after edit\n\n"
        "After editing files to address a failing test, rerun the test command "
        "and confirm it passes before reporting the work done.\n\n"
        "## Procedure\n\n"
        "1. Run the test command and note the failure.\n"
        "2. Make the fix.\n"
        f"3. Re-run `{top_cmd}` and confirm it passes.\n\n"
        f"Observed {len(cycles)} fail-edit-pass cycles across "
        f"{len(trace_ids)} trace(s).\n"
    )
    evidence = [
        Evidence(
            trace_id=trace.id, event_refs=[fail.seq, edit.seq, pass_ev.seq],
            pattern="fix_then_verify",
            excerpt=(f"{q.command(fail)} failed -> edited "
                     f"{edit.payload.get('path', '')} -> {q.command(pass_ev)} passed"),
        )
        for trace, fail, edit, pass_ev in cycles
    ]
    return [
        Finding(
            kind="skill", name="verify-after-edit", body_md=body,
            rationale=(f"{len(cycles)} fail-edit-pass cycles across "
                       f"{len(trace_ids)} trace(s); verify command `{top_cmd}`."),
            evidence=evidence, pattern="fix_then_verify", priority=10 + len(cycles),
            stats={"cycles": len(cycles)},
        )
    ]


# -- miner 4: successful build/test tool preference --------------------------

def build_preference_miner(traces: Iterable[tuple[Trace, list[TraceEvent]]]) -> list[Finding]:
    """The most frequent successful test command -> instruction."""
    successes: Counter[str] = Counter()
    evidence_events: dict[str, list[tuple[Trace, TraceEvent]]] = {}
    trace_counts: dict[str, set[str]] = {}
    for trace, events in traces:
        for ev in events:
            if ev.kind != "test.run" or not q.ok(ev):
                continue
            norm = q.norm_command(q.command(ev))
            if not norm:
                continue
            successes[norm] += 1
            trace_counts.setdefault(norm, set()).add(trace.id)
            evidence_events.setdefault(norm, []).append((trace, ev))
    if not successes:
        return []
    top_cmd, count = successes.most_common(1)[0]
    sample = evidence_events[top_cmd][:6]
    body = (
        f"# Prefer `{top_cmd}`\n\n"
        f"`{top_cmd}` is the only command with successful test runs in the "
        f"imported traces ({count} successful run(s) across "
        f"{len(trace_counts[top_cmd])} trace(s)).\n\n"
        "## When\n\n"
        "- Running or verifying tests in this project.\n"
    )
    evidence = [
        Evidence(
            trace_id=trace.id, event_refs=[ev.seq],
            pattern="command_frequency",
            excerpt=(f"{q.command(ev)} -> {ev.payload.get('passed', 0)} passed, "
                     f"{ev.payload.get('failed', 0)} failed"),
        )
        for trace, ev in sample
    ]
    return [
        Finding(
            kind="instruction", name=f"use-{slugify(top_cmd)}", body_md=body,
            rationale=(f"{count} successful `{top_cmd}` runs across "
                       f"{len(trace_counts[top_cmd])} trace(s); no successful alternatives."),
            evidence=evidence, pattern="command_frequency", priority=10,
            stats={"successes": count},
        )
    ]


# -- orchestration ------------------------------------------------------------

MINERS = (retry_loop_miner, user_correction_miner,
          fix_then_verify_miner, build_preference_miner)


def merge_findings(a: Finding, b: Finding) -> Finding:
    """Merge two findings for the same (kind, name)."""
    primary, secondary = (a, b) if a.priority >= b.priority else (b, a)
    stats = {k: a.stats.get(k, 0) + b.stats.get(k, 0)
             for k in set(a.stats) | set(b.stats)}
    body = primary.body_md
    merged_patterns = set(a.pattern.split("+")) | set(b.pattern.split("+"))
    if {"user_correction", "command_frequency"} <= merged_patterns:
        # the two signals corroborate each other; make the body say so
        corrections = stats.get("corrections", 0)
        successes = stats.get("successes", 0)
        body = primary.body_md.rstrip() + (
            f"\n\n## Corroboration\n\n{corrections} user correction(s) and "
            f"{successes} successful run(s) across imported traces.\n"
        )
    seen: set[tuple] = set()
    evidence = []
    for ev in a.evidence + b.evidence:
        key = (ev.trace_id, tuple(ev.event_refs), ev.pattern)
        if key not in seen:
            seen.add(key)
            evidence.append(ev)
    return Finding(
        kind=primary.kind, name=primary.name, body_md=body,
        rationale=f"{a.rationale} Also: {b.rationale}",
        evidence=evidence[:MAX_EVIDENCE_PER_FINDING],
        pattern=f"{a.pattern}+{b.pattern}", priority=a.priority + b.priority,
        stats=stats,
    )


def mine(store: Store, project: str | None = None) -> list[Proposal]:
    """Run all miners, merge, persist new proposals. Idempotent."""
    traces = _trace_pair(store, project)
    if not traces:
        return []
    findings: list[Finding] = []
    for miner in MINERS:
        findings.extend(miner(traces))
    merged: dict[tuple[str, str], Finding] = {}
    for finding in findings:
        key = (finding.kind, finding.name)
        merged[key] = merge_findings(merged[key], finding) if key in merged else finding
    proposals: list[Proposal] = []
    for (kind, name), finding in merged.items():
        entry = store.get_entry(kind, name)
        if entry is None:
            op, target_n = "create", None
        else:
            active = store.active_version(entry.id)
            if active is None:
                continue  # entry without active version: nothing to update against
            if active.body_md.strip() == finding.body_md.strip():
                continue  # already known; nothing new to say
            op, target_n = "update", active.n
        pid = content_id("p", kind, name, op, finding.body_md, "heuristic")
        if store.get_proposal(pid):
            continue  # deterministic id: this exact proposal already exists
        proposal = Proposal(
            id=pid, op=op, kind=kind, name=name, target_n=target_n,
            body_md=finding.body_md, rationale=finding.rationale,
            origin="heuristic", status="pending",
            evidence=finding.evidence[:MAX_EVIDENCE_PER_FINDING],
            created_at=now_utc(),
        )
        store.add_proposal(proposal)
        proposals.append(proposal)
    if proposals:
        store.log("mined", {"new_proposals": len(proposals), "traces": len(traces)})
    return proposals
