"""End-to-end CLI test: the exact model-free hackathon demo, no network."""

from typer.testing import CliRunner

from conftest import EXAMPLES
from loopsmith.cli.app import app


def _out(result) -> str:
    stderr = getattr(result, "stderr", "") or ""
    return result.output + stderr


def _invoke(runner, env, *args):
    return runner.invoke(app, list(args), env=env)


def test_full_demo_pipeline(tmp_path):
    db = str(tmp_path / "loopsmith.db")
    dist = tmp_path / "dist"
    env = {"LOOPSMITH_DB": db, "LOOPSMITH_EXPORT_DIR": str(dist)}
    runner = CliRunner()

    assert _invoke(runner, env, "init").exit_code == 0

    s1 = str(EXAMPLES / "acme-api-session1.jsonl")
    s2 = str(EXAMPLES / "acme-api-session2.jsonl")
    s3 = str(EXAMPLES / "acme-api-session3.jsonl")
    result = _invoke(runner, env, "import", s1, "--project", "acme-api")
    assert result.exit_code == 0 and "Imported" in result.output
    assert _invoke(runner, env, "import", s2, "--project", "acme-api").exit_code == 0

    # duplicate import is a no-op
    dup = _invoke(runner, env, "import", s1, "--project", "acme-api")
    assert "Already imported" in dup.output

    mined = _invoke(runner, env, "mine")
    assert mined.exit_code == 0 and "Mined 3" in mined.output

    ids = [line for line in _invoke(
        runner, env, "proposals", "list", "--format", "ids").output.splitlines() if line]
    assert len(ids) == 3

    first = ids[0]
    shown = _invoke(runner, env, "proposals", "show", first)
    assert shown.exit_code == 0 and "evidence" in shown.output

    evald = _invoke(runner, env, "eval", first)
    assert evald.exit_code == 0
    assert "not_run" in evald.output
    assert "PASS" in evald.output

    # gate: no model -> refusal without --force
    refused = _invoke(runner, env, "approve", first, "--yes")
    assert refused.exit_code == 1
    assert "refused" in _out(refused)

    promoted = _invoke(runner, env, "approve", first, "--yes", "--force")
    assert promoted.exit_code == 0 and "Promoted" in promoted.output

    for pid in ids[1:]:
        assert _invoke(runner, env, "eval", pid).exit_code == 0
        assert _invoke(runner, env, "approve", pid, "--yes", "--force").exit_code == 0

    exported = _invoke(runner, env, "export")
    assert exported.exit_code == 0
    assert (dist / "AGENTS.md").exists()
    assert (dist / "memory" / "MEMORY.md").exists()
    assert (dist / "skills" / "verify-after-edit" / "SKILL.md").exists()
    assert (dist / "loopsmith-pack.md").exists()
    assert "use-python-runtests-py" in (dist / "AGENTS.md").read_text(encoding="utf-8")

    # continual loop: new evidence arrives -> update proposal -> v2
    assert _invoke(runner, env, "import", s3, "--project", "acme-api").exit_code == 0
    remined = _invoke(runner, env, "mine")
    assert "Mined 1" in remined.output
    pending = [line for line in _invoke(
        runner, env, "proposals", "list", "--status", "pending",
        "--format", "ids").output.splitlines() if line]
    assert len(pending) == 1

    upd = pending[0]
    assert _invoke(runner, env, "eval", upd).exit_code == 0
    assert _invoke(runner, env, "approve", upd, "--yes", "--force").exit_code == 0

    history = _invoke(runner, env, "history", "instruction", "use-python-runtests-py")
    assert history.exit_code == 0 and "v2" not in history.output  # table shows 1 and 2
    assert "2" in history.output

    rolled = _invoke(runner, env, "rollback", "instruction", "use-python-runtests-py")
    assert rolled.exit_code == 0 and "Rolled back" in rolled.output

    # exporting after rollback reflects v1 again
    assert _invoke(runner, env, "export", "--format", "agents").exit_code == 0
    agents = (dist / "AGENTS.md").read_text(encoding="utf-8")
    assert "version=1" in agents

    # re-mining after the update was approved must not resurrect it
    assert "No new proposals" in _invoke(runner, env, "mine").output

    assert _invoke(runner, env, "status").exit_code == 0
    assert _invoke(runner, env, "doctor").exit_code == 0