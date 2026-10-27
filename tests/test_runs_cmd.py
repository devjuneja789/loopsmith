import json
from typer.testing import CliRunner

from conftest import make_proposal
from loopsmith.cli.app import app
from loopsmith.core.models import EvalRun, ScenarioResult
from loopsmith.core.util import now_utc


def _out(result):
    return result.output + (getattr(result, "stderr", "") or "")


def _seed(store):
    proposal = make_proposal(store, pid="p-runs", name="fix-add-hint")
    run = EvalRun(
        id="r-test", proposal_id=proposal.id, benchmark_id="default",
        benchmark_hash="abc123", model="fake-model", params={"runs": 1},
        baseline_pack_hash="base", candidate_pack_hash="cand", verdict="promote",
        summary={
            "status": "complete",
            "scenarios": [{"scenario": "fix-add", "baseline": 0.0,
                           "candidate": 1.0, "delta": 1.0}],
            "baseline_success": 0.0, "candidate_success": 1.0,
            "totals": {"baseline": {"tokens_in": 10, "tokens_out": 5, "turns": 1},
                       "candidate": {"tokens_in": 20, "tokens_out": 6, "turns": 2}},
            "static_passed": True,
            "static": [{"name": "body_well_formed", "passed": True, "reason": "ok"}],
        },
        started_at=now_utc(), finished_at=now_utc(),
    )
    store.add_eval_run(run)
    store.add_result(run.id, ScenarioResult(
        scenario_id="fix-add", arm="baseline", success=False, turns=1,
        tokens_in=10, tokens_out=5, transcript_path="runs/base.json"))
    store.add_result(run.id, ScenarioResult(
        scenario_id="fix-add", arm="candidate", success=True, turns=2,
        tokens_in=20, tokens_out=6, transcript_path="runs/cand.json"))
    return run


def test_all_eval_runs_and_getter(store):
    run = _seed(store)
    assert store.get_eval_run(run.id).verdict == "promote"
    assert [r.id for r in store.all_eval_runs()] == [run.id]
    assert store.get_eval_run("nope") is None


def test_runs_list_and_detail(tmp_path):
    from loopsmith.core.store import Store

    cli_store = Store(tmp_path / "cli.db")
    _seed(cli_store)
    cli_store.close()
    env = {"LOOPSMITH_DB": str(tmp_path / "cli.db")}

    runner = CliRunner()
    listed = runner.invoke(app, ["runs"], env=env)
    assert listed.exit_code == 0
    assert "r-test" in listed.output
    assert "promote" in listed.output
    assert "instruction/fix-add-hint" in listed.output

    detail = runner.invoke(app, ["runs", "r-test"], env=env)
    assert detail.exit_code == 0
    assert "Verdict" not in detail.output  # kv style, check values
    assert "promote" in detail.output
    assert "fix-add" in detail.output
    assert "Transcripts:" in detail.output
    assert "runs/base.json" in detail.output
    assert "runs/cand.json" in detail.output


def test_runs_unknown_id(tmp_path):
    env = {"LOOPSMITH_DB": str(tmp_path / "empty.db")}
    runner = CliRunner()
    result = runner.invoke(app, ["runs", "r-nope"], env=env)
    assert result.exit_code == 1
    assert "no run" in _out(result)


def test_runs_empty(tmp_path):
    env = {"LOOPSMITH_DB": str(tmp_path / "empty2.db")}
    result = CliRunner().invoke(app, ["runs"], env=env)
    assert result.exit_code == 0
    assert "No eval runs yet" in result.output