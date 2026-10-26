import pytest

from conftest import find_proposal
from loopsmith.core.models import Evidence, Proposal
from loopsmith.core.util import now_utc
from loopsmith.eval import gates
from loopsmith.mining import heuristics


def _proposal(**overrides):
    base = dict(
        id="p-test", op="create", kind="instruction", name="ok-name",
        body_md="# Something\n\nbody", rationale="why", origin="heuristic",
        evidence=[Evidence(trace_id="missing", event_refs=[1], pattern="x")],
        created_at=now_utc(),
    )
    base.update(overrides)
    return Proposal(**base)


def test_static_gates_pass_for_mined_proposals(populated_store):
    for proposal in heuristics.mine(populated_store):
        report = gates.static_gates(populated_store, proposal)
        assert report.passed, [c for c in report.checks if not c.passed]


def test_unresolved_evidence_fails(populated_store):
    proposal = _proposal(evidence=[Evidence(trace_id="nope", event_refs=[1], pattern="x")])
    report = gates.static_gates(populated_store, proposal)
    assert not report.passed
    assert any(c.name == "evidence_resolves" and not c.passed for c in report.checks)


def test_missing_evidence_fails(populated_store):
    report = gates.static_gates(populated_store, _proposal(evidence=[]))
    assert not report.passed


def test_bad_name_fails(populated_store):
    report = gates.static_gates(populated_store, _proposal(name="Not A Slug"))
    assert any(c.name == "name_slug" and not c.passed for c in report.checks)


def test_empty_body_fails(populated_store):
    report = gates.static_gates(populated_store, _proposal(body_md="   "))
    assert any(c.name == "body_well_formed" and not c.passed for c in report.checks)


def test_create_of_existing_entry_is_stale(populated_store):
    from conftest import promote_forced

    heuristics.mine(populated_store)
    existing = find_proposal(populated_store, "instruction", "use-make-test")
    promote_forced(populated_store, existing)
    candidate = _proposal(
        name="use-make-test", kind="instruction", op="create",
        evidence=[Evidence(trace_id=existing.evidence[0].trace_id,
                           event_refs=[1], pattern="x")],
    )
    report = gates.static_gates(populated_store, candidate)
    assert any(c.name == "target_current" and not c.passed for c in report.checks)


def test_evaluate_records_not_run_without_model(populated_store):
    proposal = heuristics.mine(populated_store)[0]
    run = gates.evaluate(populated_store, proposal.id)
    assert run.verdict == "not_run"
    assert run.summary["static_passed"] is True
    assert "no model configured" in run.summary["behavioral"]
    assert populated_store.get_proposal(proposal.id).status == "evaluated"
    assert populated_store.eval_runs_for(proposal.id) == [run]
    assert run.baseline_pack_hash != run.candidate_pack_hash


def test_evaluate_rejects_failed_static_gate(populated_store):
    proposal = heuristics.mine(populated_store)[0]
    broken = proposal.model_copy(update={
        "id": "p-broken",
        "evidence": [Evidence(trace_id="nope", event_refs=[999], pattern="x")]})
    populated_store.add_proposal(broken)
    run = gates.evaluate(populated_store, broken.id)
    assert run.verdict == "reject"
    failures = [c for c in run.summary["static"] if not c["passed"]]
    assert failures


def test_evaluate_closed_proposal_raises(populated_store):
    proposal = heuristics.mine(populated_store)[0]
    populated_store.set_proposal_status(proposal.id, "approved")
    with pytest.raises(gates.GateError):
        gates.evaluate(populated_store, proposal.id)


def test_evaluate_unknown_proposal_raises(store):
    with pytest.raises(gates.GateError):
        gates.evaluate(store, "p-nope")