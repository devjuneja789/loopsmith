"""`loopsmith runs` -- inspect recorded evaluation runs."""

import json
from typing import Optional

import typer

from loopsmith import paths
from loopsmith.cli.out import kv, print_table
from loopsmith.core.store import Store


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def runs(
    run_id: Optional[str] = typer.Argument(
        None, help="Run id (omit to list recent runs)"),
    limit: int = typer.Option(20, "--limit", "-l", min=1, max=200,
                              help="How many runs to list"),
) -> None:
    """List evaluation runs, or show one run's scenario results and transcripts."""
    store = Store(paths.db_path())
    if run_id is None:
        all_runs = store.all_eval_runs(limit=limit)
        if not all_runs:
            typer.echo("No eval runs yet -- run `loopsmith eval <proposal-id>`.")
            return
        rows = []
        for run in all_runs:
            proposal = store.get_proposal(run.proposal_id)
            label = (f"{proposal.kind}/{proposal.name}" if proposal
                     else run.proposal_id)
            summary = run.summary or {}
            rates = "-"
            if "scenarios" in summary:
                rates = (f"{_pct(summary.get('baseline_success', 0))} -> "
                         f"{_pct(summary.get('candidate_success', 0))}")
            rows.append([run.id, label, run.verdict, rates,
                         run.model or "static", f"{run.started_at:%m-%d %H:%M}"])
        print_table(["run", "proposal", "verdict", "baseline -> candidate",
                     "model", "started (UTC)"], rows)
        typer.echo("Show details: loopsmith runs <run-id>")
        return

    run = store.get_eval_run(run_id)
    if run is None:
        typer.echo(f"error: no run {run_id}", err=True)
        raise typer.Exit(1)
    proposal = store.get_proposal(run.proposal_id)
    typer.echo(f"Run {run.id}")
    kv("proposal", (f"{proposal.kind}/{proposal.name} ({proposal.id})"
                    if proposal else run.proposal_id))
    kv("verdict", run.verdict)
    kv("benchmark", f"{run.benchmark_id} (hash {run.benchmark_hash})")
    kv("model", run.model or "none (static only)")
    if run.params:
        kv("params", json.dumps(run.params))
    summary = run.summary or {}
    if summary.get("static"):
        failed = [c for c in summary["static"] if not c.get("passed")]
        kv("static gates", "passed" if not failed else f"{len(failed)} failed")
    if summary.get("scenarios"):
        print_table(
            ["scenario", "baseline", "candidate", "delta"],
            [[s["scenario"], _pct(s["baseline"]), _pct(s["candidate"]),
              f"{s['delta']:+.2f}"] for s in summary["scenarios"]],
        )
        totals = summary.get("totals", {})
        base, cand = totals.get("baseline", {}), totals.get("candidate", {})
        typer.echo(f"  success: {_pct(summary.get('baseline_success', 0))} -> "
                   f"{_pct(summary.get('candidate_success', 0))}")
        typer.echo(f"  tokens:  {base.get('tokens_in', 0) + base.get('tokens_out', 0)} -> "
                   f"{cand.get('tokens_in', 0) + cand.get('tokens_out', 0)}")
        typer.echo(f"  turns:   {base.get('turns', 0)} -> {cand.get('turns', 0)}")
        if summary.get("cached_arms"):
            typer.echo(f"  cached arms reused: {summary['cached_arms']}")
    if summary.get("behavioral"):
        kv("behavioral", summary["behavioral"])
    if summary.get("error"):
        kv("error", summary["error"])

    results = store.results_for(run.id)
    if results:
        typer.echo("Transcripts:")
        for result in results:
            typer.echo(f"  {result.arm:<10} {result.scenario_id:<22} "
                       f"success={str(result.success):<5} turns={result.turns:<2} "
                       f"{result.transcript_path or '(not recorded)'}")