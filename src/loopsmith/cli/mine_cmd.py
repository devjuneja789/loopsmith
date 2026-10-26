"""`loopsmith mine` -- run miners over imported traces."""

from typing import Optional

import typer

from loopsmith import paths
from loopsmith.cli.out import print_table


def mine(
    project: Optional[str] = typer.Option(None, "--project", "-p",
                                         help="Restrict mining to one project"),
) -> None:
    """Mine traces for evidence-cited refinement proposals."""
    from loopsmith.core.store import Store
    from loopsmith.mining import heuristics

    store = Store(paths.db_path())
    traces = store.list_traces(project=project)
    if not traces:
        typer.echo("No traces imported yet -- run `loopsmith import` first.")
        raise typer.Exit(1)
    proposals = heuristics.mine(store, project)
    if not proposals:
        typer.echo(f"No new proposals from {len(traces)} trace(s); "
                   "existing entries already cover the findings.")
        return
    typer.echo(f"Mined {len(proposals)} new proposal(s) from {len(traces)} trace(s):")
    print_table(
        ["id", "op", "kind", "name", "evidence", "patterns"],
        [[p.id, p.op, p.kind, p.name, len(p.evidence),
          ",".join(sorted({e.pattern for e in p.evidence}))] for p in proposals],
    )
    typer.echo("Review with `loopsmith proposals list` / `show <id>`.")
