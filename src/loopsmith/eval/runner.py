"""Baseline-vs-candidate A/B benchmark runner.

For each scenario and arm (baseline pack, candidate pack), the agent works
in a fresh sandbox copy of the fixture. Grading copies the sandbox again
and injects the hidden checkers, so the agent can never see or edit them.

Results are cached by (benchmark hash, pack hash, model, scenario, arm,
repetition), so re-evaluating a proposal or sharing a baseline across
proposals never re-spends API budget.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from loopsmith.core import versioning
from loopsmith.core.models import EvalRun, Proposal, ScenarioResult
from loopsmith.core.store import Store
from loopsmith.core.util import new_id, now_utc
from loopsmith.eval.agent import run_agent
from loopsmith.eval.llm import LLMError
from loopsmith.eval.scenarios import Pack, Scenario

# The fixtures document these secrets; graders set them explicitly so the
# workspace's conftest never depends on the caller's shell.
GRADE_ENV = {"ACME_TOKEN_SECRET": "grade-secret", "ACME_TIMEZONE": "UTC"}

TRANSCRIPT_LIMIT = 3000


class RunnerError(RuntimeError):
    pass


def grade(scenario: Scenario, workspace: Path, timeout_s: float = 180.0) -> tuple[bool, str]:
    """Run hidden checkers against a copy of the agent's workspace."""
    with tempfile.TemporaryDirectory(prefix="loopsmith-grade-") as tmp:
        grade_dir = Path(tmp) / "grade"
        shutil.copytree(workspace, grade_dir)
        for path in scenario.checker.rglob("*"):
            if path.is_file():
                target = grade_dir / path.relative_to(scenario.checker)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **GRADE_ENV}
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q"], cwd=grade_dir,
                capture_output=True, text=True, timeout=timeout_s, env=env)
        except subprocess.TimeoutExpired:
            return False, f"grader timed out after {timeout_s}s"
        return proc.returncode == 0, (proc.stdout + proc.stderr)[-TRANSCRIPT_LIMIT:]


def _rate(results: list[ScenarioResult], arm: str, scenario_id: str | None = None) -> float:
    subset = [r for r in results
              if r.arm == arm and (scenario_id is None or r.scenario_id == scenario_id)]
    return sum(1 for r in subset if r.success) / len(subset) if subset else 0.0


def decide_verdict(per_scenario: list[dict], baseline_rate: float,
                   candidate_rate: float) -> str:
    """Conservative: any regression rejects; ties go to baseline."""
    if any(s["candidate"] < s["baseline"] for s in per_scenario):
        return "reject"
    if candidate_rate < baseline_rate:
        return "reject"
    if candidate_rate > baseline_rate:
        return "promote"
    return "inconclusive"


def _totals(results: list[ScenarioResult], arm: str) -> dict:
    subset = [r for r in results if r.arm == arm]
    return {
        "tokens_in": sum(r.tokens_in for r in subset),
        "tokens_out": sum(r.tokens_out for r in subset),
        "turns": sum(r.turns for r in subset),
    }


def run_ab(store: Store, proposal: Proposal, pack: Pack, llm, runs: int = 1,
           max_turns: int | None = None, runs_dir: Path | None = None) -> EvalRun:
    baseline_md = versioning.pack_markdown(store)
    candidate_md = versioning.pack_markdown(store, extra=proposal)
    baseline_hash = versioning.pack_hash(baseline_md)
    candidate_hash = versioning.pack_hash(candidate_md)
    model = getattr(getattr(llm, "config", None), "model", None)

    run = EvalRun(
        id=new_id("r"), proposal_id=proposal.id, benchmark_id=pack.id,
        benchmark_hash=pack.hash, model=model,
        params={"runs": runs, "temperature": 0.0,
                "max_turns": max_turns or "scenario-default"},
        baseline_pack_hash=baseline_hash, candidate_pack_hash=candidate_hash,
        verdict="not_run", summary={"status": "running"}, started_at=now_utc(),
    )
    store.add_eval_run(run)

    results: list[ScenarioResult] = []
    cached = 0
    error: str | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="loopsmith-ab-") as tmp:
            for scenario in pack.scenarios:
                arms = (
                    ("baseline", baseline_md, baseline_hash),
                    ("candidate", candidate_md, candidate_hash),
                )
                for arm, pack_md, pack_hash in arms:
                    for run_ix in range(runs):
                        hit = store.cached_result(pack.hash, pack_hash, model,
                                                  scenario.id, arm, run_ix)
                        if hit is not None:
                            cached += 1
                            results.append(hit)
                            store.add_result(run.id, hit)
                            continue
                        sandbox = Path(tmp) / f"{scenario.id}-{arm}-{run_ix}"
                        shutil.copytree(scenario.workspace, sandbox)
                        started = time.monotonic()
                        agent_run = run_agent(llm, scenario, pack_md, sandbox,
                                              max_turns=max_turns)
                        wall = time.monotonic() - started
                        success, grader_output = grade(scenario, sandbox)
                        transcript_path = None
                        if runs_dir is not None:
                            runs_dir.mkdir(parents=True, exist_ok=True)
                            transcript = (runs_dir /
                                          f"{run.id}-{scenario.id}-{arm}-{run_ix}.json")
                            transcript.write_text(json.dumps({
                                "run_id": run.id, "scenario": scenario.id, "arm": arm,
                                "run_ix": run_ix, "success": success,
                                "grader_output": grader_output,
                                "agent": {
                                    "turns": agent_run.turns,
                                    "finished": agent_run.finished,
                                    "final_message": agent_run.final_message,
                                    "transcript": agent_run.transcript,
                                },
                            }, indent=2), encoding="utf-8")
                            transcript_path = str(transcript)
                        result = ScenarioResult(
                            scenario_id=scenario.id, arm=arm, run_ix=run_ix,
                            success=success, tokens_in=agent_run.tokens_in,
                            tokens_out=agent_run.tokens_out, turns=agent_run.turns,
                            wall_s=round(wall, 2), transcript_path=transcript_path,
                        )
                        store.add_result(run.id, result)
                        results.append(result)
    except LLMError as exc:
        error = str(exc)

    per_scenario = []
    for scenario in pack.scenarios:
        base_rate = _rate(results, "baseline", scenario.id)
        cand_rate = _rate(results, "candidate", scenario.id)
        per_scenario.append({
            "scenario": scenario.id,
            "baseline": round(base_rate, 3),
            "candidate": round(cand_rate, 3),
            "delta": round(cand_rate - base_rate, 3),
        })
    baseline_rate = _rate(results, "baseline")
    candidate_rate = _rate(results, "candidate")
    verdict = "not_run" if error else decide_verdict(
        per_scenario, baseline_rate, candidate_rate)

    run.verdict = verdict  # type: ignore[assignment]
    run.summary = {
        "status": "error" if error else "complete",
        "error": error,
        "runs": runs,
        "scenarios": per_scenario,
        "baseline_success": round(baseline_rate, 3),
        "candidate_success": round(candidate_rate, 3),
        "totals": {"baseline": _totals(results, "baseline"),
                   "candidate": _totals(results, "candidate")},
        "cached_arms": cached,
        "completed_arms": len(results),
    }
    run.finished_at = now_utc()
    store.update_eval_run(run)
    store.log("ab_run", {"run_id": run.id, "proposal_id": proposal.id,
                         "verdict": run.verdict, "benchmark": pack.id,
                         "completed_arms": len(results), "cached": cached})
    return run