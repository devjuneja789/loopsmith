"""Promotion gates.

Stage 1 (static) is deterministic and always runs: well-formedness,
evidence grounding, and target consistency. Stage 2 (behavioral A/B
against the benchmark pack) requires a configured OpenAI-compatible
model; when absent the verdict is `not_run` and approval requires an
explicit, recorded `--force` override. The P1 benchmark runner hooks in
at the marked branch of `evaluate()`.
"""

import re
from dataclasses import asdict, dataclass

from loopsmith.config import LLMConfig
from loopsmith.core import versioning
from loopsmith.core.models import EvalRun, Proposal
from loopsmith.core.store import Store
from loopsmith.core.util import new_id, now_utc

MAX_BODY_CHARS = 4000
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")


class GateError(RuntimeError):
    pass


@dataclass
class GateCheck:
    name: str
    passed: bool
    reason: str = "ok"


@dataclass
class GateReport:
    checks: list[GateCheck]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def failures(self) -> list[GateCheck]:
        return [c for c in self.checks if not c.passed]


def static_gates(store: Store, proposal: Proposal) -> GateReport:
    checks: list[GateCheck] = []

    body_ok = bool(proposal.body_md.strip()) and len(proposal.body_md) <= MAX_BODY_CHARS
    checks.append(GateCheck(
        "body_well_formed", body_ok,
        "ok" if body_ok else f"empty or over {MAX_BODY_CHARS} chars"))

    name_ok = bool(NAME_RE.match(proposal.name))
    checks.append(GateCheck(
        "name_slug", name_ok,
        "ok" if name_ok else "must be a lowercase slug (a-z, 0-9, -)"))

    bad_refs = [
        (ev.trace_id, ref)
        for ev in proposal.evidence
        for ref in ev.event_refs
        if not store.event_exists(ev.trace_id, ref)
    ]
    evidence_ok = bool(proposal.evidence) and not bad_refs
    reason = "ok"
    if not proposal.evidence:
        reason = "no evidence attached"
    elif bad_refs:
        reason = f"{len(bad_refs)} unresolved event refs: {bad_refs[:3]}"
    checks.append(GateCheck("evidence_resolves", evidence_ok, reason))

    same_name_other_kind = store.find_entry_by_name(proposal.name)
    kind_consistent = same_name_other_kind is None or same_name_other_kind.kind == proposal.kind
    checks.append(GateCheck(
        "kind_consistent", kind_consistent,
        "ok" if kind_consistent
        else f"name already used by a {same_name_other_kind.kind} entry"))

    entry = store.get_entry(proposal.kind, proposal.name)
    if proposal.op == "create":
        target_ok = entry is None
        reason = "ok" if target_ok else "entry already exists (proposal is stale)"
    else:
        active = store.active_version(entry.id) if entry else None
        target_ok = entry is not None and active is not None and active.n == proposal.target_n
        if entry is None:
            reason = "target entry does not exist"
        elif active is None:
            reason = "target entry has no active version"
        else:
            reason = ("ok" if target_ok
                      else f"targets v{proposal.target_n} but active is v{active.n}")
    checks.append(GateCheck("target_current", target_ok, reason))

    if entry is not None:
        active = store.active_version(entry.id)
        differs = not (active and active.body_md.strip() == proposal.body_md.strip())
        checks.append(GateCheck(
            "body_differs", differs,
            "ok" if differs else "identical to the active body (no-op)"))
    else:
        checks.append(GateCheck("body_differs", True, "ok"))

    return GateReport(checks=checks)


def evaluate(store: Store, proposal_id: str, llm: LLMConfig | None = None,
             benchmark: str | None = None, runs: int = 1,
             runs_dir=None, scenario_ids: list[str] | None = None) -> EvalRun:
    """Run gates on a proposal and record the verdict as an EvalRun.

    Static gates always run. When a model endpoint is configured and a
    benchmark pack is available, a behavioral A/B run decides the verdict;
    otherwise the verdict is `not_run` and approval needs `--force`.
    """
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise GateError(f"no proposal {proposal_id}")
    if proposal.status not in ("pending", "evaluated"):
        raise GateError(f"proposal is {proposal.status}; nothing to evaluate")

    started = now_utc()
    report = static_gates(store, proposal)
    static_summary = [asdict(c) for c in report.checks]
    baseline_hash = versioning.pack_hash(versioning.pack_markdown(store))
    candidate_hash = versioning.pack_hash(
        versioning.pack_markdown(store, extra=proposal))

    if not report.passed:
        run = EvalRun(
            id=new_id("r"), proposal_id=proposal.id,
            params={"stage": "static", "max_body_chars": MAX_BODY_CHARS},
            baseline_pack_hash=baseline_hash, candidate_pack_hash=candidate_hash,
            verdict="reject",
            summary={"static": static_summary, "static_passed": False,
                     "behavioral": "not reached: static gates failed"},
            started_at=started, finished_at=now_utc(),
        )
        _store_and_close(store, proposal, run)
        return run

    if llm is not None and llm.configured:
        from loopsmith.eval.llm import LLMClient
        from loopsmith.eval.runner import RunnerError, run_ab
        from loopsmith.eval.scenarios import PackError, load_pack, resolve_pack_root

        try:
            pack = load_pack(resolve_pack_root(benchmark))
        except PackError as exc:
            run = EvalRun(
                id=new_id("r"), proposal_id=proposal.id, model=llm.model,
                params={"stage": "static", "max_body_chars": MAX_BODY_CHARS},
                baseline_pack_hash=baseline_hash, candidate_pack_hash=candidate_hash,
                verdict="not_run",
                summary={"static": static_summary, "static_passed": True,
                         "behavioral": f"benchmark unavailable: {exc}"},
                started_at=started, finished_at=now_utc(),
            )
            _store_and_close(store, proposal, run)
            return run

        if scenario_ids:
            known = {scenario.id for scenario in pack.scenarios}
            unknown = [sid for sid in scenario_ids if sid not in known]
            if unknown:
                raise GateError(
                    f"unknown scenario ids {unknown}; pack '{pack.id}' has {sorted(known)}")

        client = LLMClient(llm)
        try:
            run = run_ab(store, proposal, pack, client, runs=runs,
                         runs_dir=runs_dir, scenario_ids=scenario_ids)
        except RunnerError as exc:
            raise GateError(str(exc)) from exc
        run.summary["static"] = static_summary
        run.summary["static_passed"] = True
        run.summary.setdefault("behavioral", "A/B benchmark")
        store.update_eval_run(run)
        _close(store, proposal, run)
        return run

    run = EvalRun(
        id=new_id("r"), proposal_id=proposal.id,
        params={"stage": "static", "max_body_chars": MAX_BODY_CHARS},
        baseline_pack_hash=baseline_hash, candidate_pack_hash=candidate_hash,
        verdict="not_run",
        summary={"static": static_summary, "static_passed": True,
                 "behavioral": "skipped: no model configured; approval requires --force"},
        started_at=started, finished_at=now_utc(),
    )
    _store_and_close(store, proposal, run)
    return run


def _store_and_close(store: Store, proposal: Proposal, run: EvalRun) -> None:
    store.add_eval_run(run)
    _close(store, proposal, run)


def _close(store: Store, proposal: Proposal, run: EvalRun) -> None:
    store.set_proposal_status(proposal.id, "evaluated")
    store.log("evaluated", {
        "proposal_id": proposal.id, "verdict": run.verdict,
        "static_passed": bool(run.summary.get("static_passed")),
        "model": run.model,
    })
