from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import EXAMPLES
from loopsmith.cli.app import app
from loopsmith.core.store import Store
from loopsmith.mining.heuristics import build_preference_miner
from loopsmith.traces.schema import TraceEvent


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LOOPSMITH_DB", raising=False)
    return tmp_path


def test_review_apply_from_other_repo(repo):
    runner = CliRunner()
    session = str(EXAMPLES / "codex-command-review.jsonl")
    target = Path("AGENTS.md")
    target.write_text("# Existing notes\n", encoding="utf-8")
    args = ["review", "--session", session]
    for _ in range(2):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.exception
        assert "Static checks passed" in result.output
        assert target.read_text() == "# Existing notes\n"
    store = Store(repo / ".loopsmith/loopsmith.db")
    proposal, = store.list_proposals()
    assert proposal.evidence[0].event_refs == [2, 3, 4]
    assert len(store.eval_runs_for(proposal.id)) == 1
    assert runner.invoke(app, ["approve", proposal.id, "--yes", "--force"]).exit_code == 0
    export = ["export", "--format", "agents", "--out", "."]
    assert runner.invoke(app, export).exit_code == 0
    applied = target.read_bytes()
    assert applied.startswith(b"# Existing notes")
    assert proposal.body_md in target.read_text()
    assert runner.invoke(app, export).exit_code == 0
    assert target.read_bytes() == applied
    assert "No new reusable" in runner.invoke(app, args).output


@pytest.mark.parametrize("replacement", ["Process exited with code 1", "unknown status"])
def test_review_requires_success(repo, replacement):
    session = repo / "selected.jsonl"
    session.write_text((EXAMPLES / "codex-command-review.jsonl").read_text().replace(
        "Process exited with code 0", replacement))
    result = CliRunner().invoke(app, ["review", "--session", str(session)])
    assert result.exit_code == 0 and "No new reusable" in result.output
    assert not Path("AGENTS.md").exists()


def test_multiple_successful_commands_do_not_establish_preference(populated_store):
    trace, _ = populated_store.all_events_by_trace()[0]
    events = [TraceEvent(seq=i, kind="test.run", payload={"command": cmd, "exit_code": 0,
                                                           "failed": 0})
              for i, cmd in enumerate(["pytest", "make test"], 1)]
    assert build_preference_miner([(trace, events)]) == []
