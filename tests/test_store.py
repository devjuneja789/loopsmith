from datetime import datetime, timezone

from loopsmith.core.models import Proposal
from loopsmith.core.store import Store
from loopsmith.core.util import now_utc
from loopsmith.traces.schema import SessionMeta, Trace, TraceEvent


def _trace(trace_id="t1"):
    return Trace(id=trace_id, source="loopsmith-jsonl", project="p",
                 session=SessionMeta(agent="a", model="m"), imported_at=now_utc())


def _events():
    return [
        TraceEvent(seq=1, kind="user.message", payload={"text": "hi"}),
        TraceEvent(seq=2, kind="test.run",
                   payload={"command": "make test", "passed": 1, "failed": 0, "exit_code": 0}),
    ]


def test_save_and_read_trace(store):
    store.save_trace(_trace(), _events())
    assert store.trace_exists("t1")
    assert not store.trace_exists("t2")
    summaries = store.list_traces()
    assert len(summaries) == 1
    assert summaries[0].n_events == 2
    events = store.trace_events("t1")
    assert [e.kind for e in events] == ["user.message", "test.run"]
    assert events[1].payload["command"] == "make test"
    assert store.event_exists("t1", 2)
    assert not store.event_exists("t1", 99)


def test_entries_and_versions_autoincrement(store):
    entry = store.create_entry("memory", "flaky-x", "desc")
    v1 = store.add_version(entry.id, "body 1", "why", "active")
    assert v1.n == 1
    store.set_version_status(v1.id, "superseded")
    v2 = store.add_version(entry.id, "body 2", "why", "active")
    assert v2.n == 2
    assert store.active_version(entry.id).n == 2
    assert [v.n for v in store.versions(entry.id)] == [1, 2]


def test_proposal_roundtrip(store):
    from loopsmith.core.models import Evidence

    proposal = Proposal(
        id="p1", op="create", kind="instruction", name="use-make-test",
        body_md="# Use make test", rationale="r", origin="heuristic",
        evidence=[Evidence(trace_id="t1", event_refs=[1], pattern="x", excerpt="e")],
        created_at=now_utc(),
    )
    store.add_proposal(proposal)
    loaded = store.get_proposal("p1")
    assert loaded is not None
    assert loaded.evidence[0].event_refs == [1]
    assert store.list_proposals(status="pending")[0].id == "p1"
    store.set_proposal_status("p1", "approved")
    assert store.get_proposal("p1").status == "approved"
    assert store.list_proposals(status="pending") == []


def test_audit_log(store):
    store.log("custom", {"a": 1})
    events = store.audit()
    assert events[0].kind == "custom"
    assert events[0].payload == {"a": 1}
    assert any(e.kind == "db_initialized" for e in events)


def test_active_version_uniqueness_enforced(store):
    import sqlite3

    import pytest

    entry = store.create_entry("memory", "m", None)
    store.add_version(entry.id, "b1", None, "active")
    with pytest.raises(sqlite3.IntegrityError):
        # bypass the helper and insert a second active row directly
        store._conn.execute(
            "INSERT INTO entry_versions (id, entry_id, n, body_md, rationale, status, created_at)"
            " VALUES ('vx', ?, 2, 'b2', NULL, 'active', ?)",
            (entry.id, datetime.now(timezone.utc).isoformat()),
        )