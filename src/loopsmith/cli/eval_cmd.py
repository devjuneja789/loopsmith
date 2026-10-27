"""`loopsmith eval` -- run promotion gates on a proposal."""

from typing import Optional

import typer

from loopsmith import config, paths
from loopsmith.cli.out import print_table
from loopsmith.core.store import Store


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def evaluate(
    proposal_id: str = typer.Argument(..., help="Proposal id"),
    runs: int = typer.Option(1, "--runs", "-n", min=1, max=5,
                             help="A/B repetitions per arm (each one costs API budget)"),
    benchmark: Optional[str] = typer.Option(
        None, "--benchmark", "-b",
        help="Benchmark pack directory (default: benchmarks/default)"),
    scenario: Optional[list[str]] = typer.Option(
        None, "--scenario", "-s",
        help="Run only these scenario ids (repeatable; saves API budget)"),
) -> None:
    """Run static gates; with a configured model, also run the A/B benchmark."""
    from loopsmith.eval import gates
    from loopsmith.eval.llm import LLMError

    store = Store(paths.db_path())
    try:
        run = gates.evaluate(store, proposal_id, llm=config.load_llm_config(),
                             benchmark=benchmark, runs=runs,
                             runs_dir=paths.runs_dir(), scenario_ids=scenario)
    except (gates.GateError, LLMError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Eval run {run.id} for proposal {proposal_id}")
    typer.echo("Static gates:")
    print_table(
        ["gate", "result", "detail"],
        [[c["name"], "PASS" if c["passed"] else "FAIL", c["reason"]]
         for c in run.summary.get("static", [])],
    )

    scenarios = run.summary.get("scenarios")
    if scenarios:
        typer.echo(f"\nBehavioral A/B on '{run.benchmark_id}' "
                   f"(model {run.model}, runs={run.params.get('runs')}):")
        print_table(
            ["scenario", "baseline", "candidate", "delta"],
            [[s["scenario"], _pct(s["baseline"]), _pct(s["candidate"]),
              f"{s['delta']:+.2f}"] for s in scenarios],
        )
        totals = run.summary.get("totals", {})
        base, cand = totals.get("baseline", {}), totals.get("candidate", {})
        typer.echo(f"  success: {_pct(run.summary.get('baseline_success', 0))} -> "
                   f"{_pct(run.summary.get('candidate_success', 0))}")
        typer.echo(f"  tokens:  {base.get('tokens_in', 0) + base.get('tokens_out', 0)} -> "
                   f"{cand.get('tokens_in', 0) + cand.get('tokens_out', 0)}")
        typer.echo(f"  turns:   {base.get('turns', 0)} -> {cand.get('turns', 0)}")
        if run.summary.get("cached_arms"):
            typer.echo(f"  cached arms reused: {run.summary['cached_arms']}")
        if run.summary.get("error"):
            typer.echo(f"  error: {run.summary['error']}", err=True)
    else:
        typer.echo(f"\nBehavioral: {run.summary.get('behavioral')}")
    typer.echo(f"Verdict:    {run.verdict}")

    if run.verdict == "not_run":
        typer.echo("Promote with `loopsmith approve --force` (recorded override), "
                   "or configure LOOPSMITH_LLM_* for behavioral evaluation.")
    elif run.verdict == "promote":
        typer.echo("Promote with `loopsmith approve`.")
    elif run.verdict == "reject":
        typer.echo("Blocked: re-mine or write a new proposal.")
    elif run.verdict == "inconclusive":
        typer.echo("No measurable gain (ties go to baseline). Approve only with --force.")