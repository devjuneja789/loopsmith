from conftest import find_proposal
from loopsmith.mining import heuristics


def test_mine_produces_expected_three(populated_store):
    proposals = heuristics.mine(populated_store)
    assert len(proposals) == 3
    names = {(p.kind, p.name) for p in proposals}
    assert names == {
        ("instruction", "use-python-runtests-py"),
        ("memory", "flaky-test-auth-login"),
        ("skill", "verify-after-edit"),
    }


def test_all_evidence_refs_resolve(populated_store):
    for proposal in heuristics.mine(populated_store):
        assert proposal.evidence, "every proposal must be evidence-grounded"
        for ev in proposal.evidence:
            for ref in ev.event_refs:
                assert populated_store.event_exists(ev.trace_id, ref), (
                    f"unresolved ref {ev.trace_id}#{ref}")


def test_flaky_memory_cites_the_retry_loop(populated_store):
    heuristics.mine(populated_store)
    proposal = find_proposal(populated_store, "memory", "flaky-test-auth-login")
    refs = sorted(r for ev in proposal.evidence for r in ev.event_refs)
    assert refs == [3, 4, 5]


def test_skill_merges_all_fix_verify_cycles(populated_store):
    heuristics.mine(populated_store)
    proposal = find_proposal(populated_store, "skill", "verify-after-edit")
    assert len(proposal.evidence) == 2
    assert "python runtests.py" in proposal.body_md


def test_instruction_merges_correction_and_frequency(populated_store):
    heuristics.mine(populated_store)
    proposal = find_proposal(populated_store, "instruction", "use-python-runtests-py")
    patterns = {ev.pattern for ev in proposal.evidence}
    assert patterns == {"user_correction", "command_frequency"}
    assert "Corroboration" in proposal.body_md
    assert "3 successful run(s)" in proposal.body_md


def test_mining_is_idempotent(populated_store):
    first = heuristics.mine(populated_store)
    assert len(first) == 3
    second = heuristics.mine(populated_store)
    assert second == []
    assert len(populated_store.list_proposals()) == 3


def test_new_evidence_yields_update_proposal(populated_store):
    from conftest import EXAMPLES

    from loopsmith.traces import importers

    heuristics.mine(populated_store)
    for proposal in populated_store.list_proposals():
        from loopsmith.core import versioning

        versioning.promote(populated_store, proposal, forced=True)

    importers.ingest(populated_store, EXAMPLES / "acme-api-session3.jsonl",
                     "acme-api", "loopsmith")
    new = heuristics.mine(populated_store)
    assert len(new) == 1
    assert new[0].op == "update"
    assert new[0].name == "use-python-runtests-py"
    assert new[0].target_n == 1
    assert "2 user correction(s)" in new[0].body_md


def test_mining_without_traces_is_empty(store):
    assert heuristics.mine(store) == []


def test_slugify():
    assert heuristics.slugify("python runtests.py -k test_auth_login") == "python-runtests-py-k-test-auth-login"
    assert heuristics.slugify("!!!") == "unnamed"