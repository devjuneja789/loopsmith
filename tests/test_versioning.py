import pytest

from conftest import find_proposal, promote_forced
from loopsmith.core import versioning
from loopsmith.core.models import Proposal
from loopsmith.core.util import now_utc
from loopsmith.mining import heuristics


def test_promote_create_makes_active_v1(populated_store):
    proposals = heuristics.mine(populated_store)
    target = next(p for p in proposals if p.kind == "instruction")
    version = promote_forced(populated_store, target)
    assert version.n == 1
    entry = populated_store.get_entry("instruction", "use-make-test")
    assert entry is not None
    active = populated_store.active_version(entry.id)
    assert active.id == version.id
    assert populated_store.get_proposal(target.id).status == "approved"
    assert any(e.kind == "approved" for e in populated_store.audit())


def test_promote_twice_is_refused(populated_store):
    proposal = heuristics.mine(populated_store)[0]
    promote_forced(populated_store, proposal)
    with pytest.raises(versioning.VersioningError):
        promote_forced(populated_store, proposal)


def test_update_supersedes_and_bumps(populated_store):
    heuristics.mine(populated_store)
    create = find_proposal(populated_store, "instruction", "use-make-test")
    promote_forced(populated_store, create)
    update = Proposal(
        id="p-upd", op="update", kind="instruction", name="use-make-test",
        target_n=1, body_md="# Use `make test`\n\nv2 body.\n", rationale="more evidence",
        origin="heuristic", status="pending", evidence=create.evidence,
        created_at=now_utc(),
    )
    populated_store.add_proposal(update)
    version = promote_forced(populated_store, update)
    assert version.n == 2
    entry = populated_store.get_entry("instruction", "use-make-test")
    versions = populated_store.versions(entry.id)
    assert [v.status for v in versions] == ["superseded", "active"]


def test_stale_target_is_refused(populated_store):
    heuristics.mine(populated_store)
    create = find_proposal(populated_store, "instruction", "use-make-test")
    promote_forced(populated_store, create)
    stale = Proposal(
        id="p-stale", op="update", kind="instruction", name="use-make-test",
        target_n=99, body_md="# x\n\nstale\n", rationale="r", origin="heuristic",
        status="pending", evidence=create.evidence, created_at=now_utc(),
    )
    populated_store.add_proposal(stale)
    with pytest.raises(versioning.VersioningError, match="stale"):
        promote_forced(populated_store, stale)


def test_noop_update_is_refused(populated_store):
    heuristics.mine(populated_store)
    create = find_proposal(populated_store, "instruction", "use-make-test")
    promote_forced(populated_store, create)
    noop = Proposal(
        id="p-noop", op="update", kind="instruction", name="use-make-test",
        target_n=1, body_md=create.body_md, rationale="r", origin="heuristic",
        status="pending", evidence=create.evidence, created_at=now_utc(),
    )
    populated_store.add_proposal(noop)
    with pytest.raises(versioning.VersioningError, match="no-op"):
        promote_forced(populated_store, noop)


def test_rollback_moves_the_pointer(populated_store):
    heuristics.mine(populated_store)
    create = find_proposal(populated_store, "instruction", "use-make-test")
    promote_forced(populated_store, create)
    update = Proposal(
        id="p-upd", op="update", kind="instruction", name="use-make-test",
        target_n=1, body_md="# Use `make test`\n\nv2 body.\n", rationale="r",
        origin="heuristic", status="pending", evidence=create.evidence,
        created_at=now_utc(),
    )
    populated_store.add_proposal(update)
    promote_forced(populated_store, update)

    rolled = versioning.rollback(populated_store, "instruction", "use-make-test")
    assert rolled.n == 1
    entry = populated_store.get_entry("instruction", "use-make-test")
    assert populated_store.active_version(entry.id).n == 1
    assert [v.status for v in populated_store.versions(entry.id)] == ["active", "reverted"]
    assert any(e.kind == "rolled_back" for e in populated_store.audit())
    # rollback is itself reversible: going forward again is allowed
    again = versioning.rollback(populated_store, "instruction", "use-make-test", to_n=2)
    assert again.n == 2


def test_rollback_with_single_version_is_refused(populated_store):
    heuristics.mine(populated_store)
    create = find_proposal(populated_store, "instruction", "use-make-test")
    promote_forced(populated_store, create)
    with pytest.raises(versioning.VersioningError, match="no earlier version"):
        versioning.rollback(populated_store, "instruction", "use-make-test")


def test_pack_markdown_candidate_differs(populated_store):
    proposal = heuristics.mine(populated_store)[0]
    baseline = versioning.pack_markdown(populated_store)
    candidate = versioning.pack_markdown(populated_store, extra=proposal)
    assert baseline != candidate
    assert versioning.pack_hash(baseline) != versioning.pack_hash(candidate)
    assert proposal.name in candidate