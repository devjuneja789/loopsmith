import json

from conftest import FakeLLM
from loopsmith.eval.llm_miner import mine_with_llm


def _grounded(trace_id):
    return {
        "op": "create", "kind": "memory", "name": "Check DB reset ordering",
        "body_md": "# Check DB reset ordering\n\nReset the fixture DB before the login assertion.\n",
        "rationale": "repeated fixture-ordering failures",
        "evidence": [{"trace_id": trace_id, "event_refs": [1], "pattern": "llm",
                      "excerpt": "fixture ordering"}],
    }


def test_only_grounded_proposals_persist(populated_store):
    trace_id = populated_store.list_traces()[0].id
    payload = {"proposals": [
        _grounded(trace_id),
        {**_grounded(trace_id), "name": "Ungrounded", "evidence": [
            {"trace_id": "missing", "event_refs": [1]}]},
        {**_grounded(trace_id), "name": "Empty body", "body_md": "   "},
        {**_grounded(trace_id), "kind": "subagent", "name": "bad-kind"},
    ]}
    created = mine_with_llm(populated_store, FakeLLM([json.dumps(payload)]))
    assert len(created) == 1
    proposal = created[0]
    assert proposal.origin == "llm"
    assert proposal.name == "check-db-reset-ordering"
    assert proposal.evidence[0].event_refs == [1]


def test_llm_mining_is_idempotent(populated_store):
    trace_id = populated_store.list_traces()[0].id
    payload = json.dumps({"proposals": [_grounded(trace_id)]})
    assert len(mine_with_llm(populated_store, FakeLLM([payload]))) == 1
    assert mine_with_llm(populated_store, FakeLLM([payload])) == []


def test_max_proposals_is_capped(populated_store):
    trace_id = populated_store.list_traces()[0].id
    items = [{**_grounded(trace_id), "name": f"memory-{i}"} for i in range(6)]
    created = mine_with_llm(populated_store,
                            FakeLLM([json.dumps({"proposals": items})]), max_proposals=2)
    assert len(created) == 2


def test_malformed_reply_is_ignored(populated_store):
    assert mine_with_llm(populated_store, FakeLLM(["not json at all"])) == []
    assert mine_with_llm(populated_store, FakeLLM(['{"proposals": "nope"}'])) == []


def test_no_traces_means_no_calls(store):
    llm = FakeLLM()
    assert mine_with_llm(store, llm) == []
    assert llm.calls == []