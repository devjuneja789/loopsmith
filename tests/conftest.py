import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from loopsmith.core.store import Store

# Hermetic tests: never read the developer's .env (it may hold a real key).
os.environ.setdefault("LOOPSMITH_SKIP_DOTENV", "1")

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples" / "traces"
SESSIONS = ("acme-api-session1.jsonl", "acme-api-session2.jsonl")


class FakeLLM:
    """Scripted stand-in for LLMClient.

    `responses` is a queue of str or callable(messages); each entry is
    consumed once. `responder` is a persistent callable consulted first,
    for multi-arm scripts that must react to every call.
    """

    def __init__(self, responses=None, model="fake-model", responder=None):
        self.responses = list(responses or [])
        self.responder = responder
        self.calls: list[list[dict]] = []
        self.config = SimpleNamespace(model=model)

    def chat(self, messages, temperature=0.0, max_tokens=1200):
        from loopsmith.eval.llm import ChatResult

        self.calls.append(messages)
        if self.responder is not None:
            text = self.responder(messages)
        elif self.responses:
            item = self.responses.pop(0)
            text = item(messages) if callable(item) else item
        else:
            text = '{"tool": "finish", "args": {"summary": "done"}}'
        return ChatResult(text=text, usage={"prompt_tokens": 10, "completion_tokens": 5})


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


@pytest.fixture()
def tiny_pack(tmp_path):
    """A one-scenario pack whose checker only passes after app/mathx.py is fixed."""
    from loopsmith.eval.scenarios import load_pack

    root = tmp_path / "tiny-pack"
    scenario = root / "scenarios" / "fix-add"
    (scenario / "workspace" / "app").mkdir(parents=True)
    (scenario / "checker").mkdir(parents=True)
    (scenario / "task.md").write_text(
        "# Fix add\n\napp/mathx.py add() returns the wrong result.\n", encoding="utf-8")
    (scenario / "workspace" / "app" / "__init__.py").write_text("", encoding="utf-8")
    (scenario / "workspace" / "app" / "mathx.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8")
    (scenario / "checker" / "test_hidden.py").write_text(
        "from app.mathx import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8")
    return load_pack(root)


def find_proposal(store, kind, name):
    for proposal in store.list_proposals():
        if proposal.kind == kind and proposal.name == name:
            return proposal
    raise AssertionError(f"no proposal {kind}/{name}")


def promote_forced(store, proposal, forced=True):
    from loopsmith.core import versioning

    return versioning.promote(store, proposal, forced=forced)


def make_proposal(store, body_md="# Fix add\n\n`app/mathx.py` should add instead of subtract.\n",
                  pid="p-ab", kind="instruction", name="fix-add-hint"):
    from loopsmith.core.models import Proposal
    from loopsmith.core.util import now_utc

    proposal = Proposal(
        id=pid, op="create", kind=kind, name=name, body_md=body_md,
        rationale="test proposal", origin="heuristic", created_at=now_utc(),
    )
    store.add_proposal(proposal)
    return proposal