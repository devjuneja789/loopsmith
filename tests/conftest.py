from pathlib import Path

import pytest

from loopsmith.core.store import Store

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples" / "traces"
SESSIONS = ("acme-api-session1.jsonl", "acme-api-session2.jsonl")


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "loopsmith.db")
    yield s
    s.close()


@pytest.fixture()
def populated_store(store):
    from loopsmith.traces import importers

    for name in SESSIONS:
        importers.ingest(store, EXAMPLES / name, "acme-api", "loopsmith")
    return store


def find_proposal(store, kind, name):
    for proposal in store.list_proposals():
        if proposal.kind == kind and proposal.name == name:
            return proposal
    raise AssertionError(f"no proposal {kind}/{name}")


def promote_forced(store, proposal, forced=True):
    from loopsmith.core import versioning

    return versioning.promote(store, proposal, forced=forced)