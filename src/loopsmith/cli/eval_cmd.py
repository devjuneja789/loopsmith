"""`loopsmith eval` -- run promotion gates on a proposal."""

import typer

from loopsmith import paths, config
from loopsmith.cli.out import print_table
from loopsmith.core.store import Store


def evaluate(
    proposal_id: str = typer.Argument(..., help="Proposal id"),
) -> None:
    """Run static gates (and, once P1 lands, the behavioral A/B benchmark)."""
    from loopsmith.eval import gates

    store = Store(paths.db_path())
    try:
        run = gates.evaluate(store, proposal_id, llm=config.load_llm_config())
    except gates.GateError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Eval run {run.id} for proposal {proposal_id}")
    typer.echo("Static gates:")
    print_table(
        ["gate", "result", "detail"],
        [[c["name"], "PASS" if c["passed"] else "FAIL", c["reason"]]
         for c in run.summary["static"]],
    )
    typer.echo(f"Behavioral: {run.summary['behavioral']}")
    typer.echo(f"Verdict:    {run.verdict}")
    if run.verdict == "not_run":
        typer.echo("Promote with `loopsmith approve --force` (the override is recorded), "
                   "or configure LOOPSMITH_LLM_* for behavioral evaluation.")
