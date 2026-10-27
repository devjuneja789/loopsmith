import json

from conftest import FakeLLM, make_proposal
from loopsmith.eval.runner import decide_verdict, grade, run_ab

TRIGGER = "add instead of subtract"


def _scripted(fix_on_candidate: bool):
    """Baseline vs candidate behavior keyed on the harness text in the system prompt."""
    state: dict[str, int] = {}

    def respond(messages):
        has_hint = TRIGGER in messages[0]["content"]
        key = "cand" if has_hint else "base"
        state[key] = state.get(key, 0) + 1
        should_fix = has_hint if fix_on_candidate else not has_hint
        if should_fix and state[key] == 1:
            return json.dumps({
                "tool": "write_file",
                "args": {"path": "app/mathx.py",
                         "content": "def add(a, b):\n    return a + b\n"},
            })
        return json.dumps({"tool": "finish", "args": {"summary": "done"}})

    return respond


def test_grade_fails_on_pristine_fixture(tiny_pack):
    scenario = tiny_pack.scenarios[0]
    success, output = grade(scenario, scenario.workspace)
    assert not success
    assert "assert" in output or "failed" in output


def test_ab_promotes_when_candidate_wins(store, tiny_pack):
    proposal = make_proposal(store)
    run = run_ab(store, proposal, tiny_pack, FakeLLM(responder=_scripted(fix_on_candidate=True)))
    assert run.verdict == "promote"
    assert run.summary["baseline_success"] == 0.0
    assert run.summary["candidate_success"] == 1.0
    assert run.summary["scenarios"][0]["delta"] == 1.0
    assert run.benchmark_hash == tiny_pack.hash
    assert run.model == "fake-model"
    results = store.results_for(run.id)
    assert len(results) == 2
    assert {r.arm for r in results} == {"baseline", "candidate"}


def test_ab_rejects_on_regression(store, tiny_pack):
    proposal = make_proposal(store)
    run = run_ab(store, proposal, tiny_pack, FakeLLM(responder=_scripted(fix_on_candidate=False)))
    assert run.verdict == "reject"
    assert run.summary["scenarios"][0]["delta"] == -1.0


def test_ab_ties_go_to_baseline(store, tiny_pack):
    proposal = make_proposal(store)
    llm = FakeLLM([
        json.dumps({"tool": "finish", "args": {"summary": "stuck"}}),
        json.dumps({"tool": "finish", "args": {"summary": "stuck"}}),
    ])
    run = run_ab(store, proposal, tiny_pack, llm)
    assert run.verdict == "inconclusive"
    assert run.summary["baseline_success"] == run.summary["candidate_success"] == 0.0


def test_ab_reuses_cached_arms(store, tiny_pack):
    proposal = make_proposal(store)
    first = run_ab(store, proposal, tiny_pack, FakeLLM(responder=_scripted(True)))
    assert first.summary["cached_arms"] == 0

    second_llm = FakeLLM()
    second = run_ab(store, proposal, tiny_pack, second_llm)
    assert second.summary["cached_arms"] == 2
    assert second_llm.calls == []
    assert second.verdict == "promote"


def test_ab_records_transcripts(store, tiny_pack, tmp_path):
    proposal = make_proposal(store)
    runs_dir = tmp_path / "runs"
    run = run_ab(store, proposal, tiny_pack, FakeLLM(responder=_scripted(True)),
                 runs_dir=runs_dir)
    files = sorted(p.name for p in runs_dir.iterdir())
    assert len(files) == 2
    assert any(name.startswith(run.id) for name in files)
    payload = json.loads((runs_dir / files[0]).read_text(encoding="utf-8"))
    assert payload["scenario"] == "fix-add"
    assert "transcript" in payload["agent"]


def test_decide_verdict_matrix():
    no_regression = [{"scenario": "a", "baseline": 0.0, "candidate": 1.0, "delta": 1.0}]
    regression = [{"scenario": "a", "baseline": 1.0, "candidate": 0.0, "delta": -1.0}]
    tie = [{"scenario": "a", "baseline": 0.0, "candidate": 0.0, "delta": 0.0}]
    assert decide_verdict(no_regression, 0.0, 1.0) == "promote"
    assert decide_verdict(regression, 1.0, 0.0) == "reject"
    assert decide_verdict(tie, 0.5, 0.5) == "inconclusive"
    # aggregate gain but one scenario regresses -> reject
    mixed = [{"scenario": "a", "baseline": 1.0, "candidate": 0.0, "delta": -1.0},
             {"scenario": "b", "baseline": 0.0, "candidate": 1.0, "delta": 1.0}]
    assert decide_verdict(mixed, 0.5, 0.5) == "reject"