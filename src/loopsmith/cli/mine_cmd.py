"""`loopsmith mine` -- run miners over imported traces."""

from typing import Optional

import typer

from loopsmith import paths
from loopsmith.cli.out import print_table


def mine(
    project: Optional[str] = typer.Option(None, "--project", "-p",
                                           help="Restrict mining to one project"),
    llm: bool = typer.Option(False, "--llm",
                             help="Also ask the configured model for proposals"),
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

    if llm:
        from loopsmith import config
        from loopsmith.eval.llm import LLMClient, LLMError
        from loopsmith.eval.llm_miner import mine_with_llm

        llm_config = config.load_llm_config()
        if not llm_config.configured:
            typer.echo("error: --llm needs LOOPSMITH_LLM_BASE_URL, "
                       "LOOPSMITH_LLM_API_KEY and LOOPSMITH_LLM_MODEL", err=True)
            raise typer.Exit(1)
        try:
            proposals += mine_with_llm(store, LLMClient(llm_config))
        except LLMError as exc:
            typer.echo(f"llm mining failed: {exc}", err=True)
            raise typer.Exit(1)

    if not proposals:
        typer.echo(f"No new proposals from {len(traces)} trace(s); "
                   "existing entries already cover the findings.")
        return
    typer.echo(f"Mined {len(proposals)} new proposal(s) from {len(traces)} trace(s):")
    print_table(
        ["id", "op", "kind", "name", "origin", "evidence", "patterns"],
        [[p.id, p.op, p.kind, p.name, p.origin, len(p.evidence),
          ",".join(sorted({e.pattern for e in p.evidence}))] for p in proposals],
    )
    typer.echo("Review with `loopsmith proposals list` / `show <id>`.")