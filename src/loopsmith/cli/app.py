"""Typer root application."""

from pathlib import Path

import typer

from loopsmith import __version__, paths
from loopsmith.cli import (
    approve_cmd,
    benchmark_cmd,
    eval_cmd,
    export_cmd,
    mine_cmd,
    proposals_cmd,
    traces_cmd,
)
from loopsmith.cli.out import kv

app = typer.Typer(
    help="LoopSmith: evaluation-gated continual harness for coding agents.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(traces_cmd.app, name="traces", help="Inspect imported traces")
app.add_typer(proposals_cmd.app, name="proposals", help="Review refinement proposals")
app.add_typer(benchmark_cmd.app, name="benchmark",
              help="Inspect and smoke-test the eval scenario pack")
app.command(name="mine")(mine_cmd.mine)
app.command(name="eval")(eval_cmd.evaluate)
app.command(name="approve")(approve_cmd.approve)
app.command(name="rollback")(approve_cmd.rollback)
app.command(name="history")(approve_cmd.history)
app.command(name="export")(export_cmd.export)


@app.command("init")
def init_() -> None:
    """Create the LoopSmith database and workspace directories."""
    from loopsmith.core.store import Store

    store = Store(paths.db_path())
    typer.echo(f"Initialized {paths.db_path()} (schema v1)")
    typer.echo(f"  traces:    {len(store.list_traces())}")
    typer.echo(f"  entries:  {len(store.list_entries())}")


@app.command("import")
def import_(
    path: Path = typer.Argument(..., exists=True, readable=True,
                               help="Trace file (JSONL)"),
    project: str = typer.Option(None, "--project", "-p",
                                help="Project label (default LOOPSMITH_PROJECT)"),
    format: str = typer.Option("auto", "--format", "-f",
                               help="auto | loopsmith | generic"),
) -> None:
    """Import a structured coding-session trace."""
    from loopsmith.core.store import Store
    from loopsmith.traces import importers

    store = Store(paths.db_path())
    result = importers.ingest(store, path, project or paths.default_project(), format)
    if result.duplicate:
        typer.echo(f"Already imported as {result.trace_id}; skipped.")
    else:
        typer.echo(
            f"Imported {path.name} -> {result.trace_id} "
            f"({result.events} events, {result.skipped} skipped, "
            f"source={result.source}, project={result.project})")


@app.command()
def doctor() -> None:
    """Check environment, database, and model endpoint configuration."""
    from loopsmith import config

    typer.echo(f"loopsmith {__version__}")
    kv("db path", paths.db_path())
    db = paths.db_path()
    if db.exists():
        from loopsmith.core.store import Store

        store = Store(db)
        kv("traces", len(store.list_traces()))
        kv("entries", len(store.list_entries()))
        kv("proposals", len(store.list_proposals()))
    else:
        typer.echo("  db:              not created yet (run `loopsmith init`)")

    llm = config.load_llm_config()
    if llm.configured:
        kv("llm endpoint", llm.base_url)
        kv("llm model", llm.model)
        kv("llm key", "set (hidden)")
        typer.echo("  note:            behavioral A/B eval is P1; static gates are live")
    else:
        typer.echo("  llm:             not configured (static gates only; "
                   "approval needs --force)")
        typer.echo("  recommended:     set LOOPSMITH_LLM_* (see .env.example) -- "
                   f"e.g. model {config.RECOMMENDED_LLM_MODELS[0]}")


@app.command()
def status() -> None:
    """Summarize the current LoopSmith state."""
    from loopsmith.core.store import Store

    db = paths.db_path()
    if not db.exists():
        typer.echo("No database yet -- run `loopsmith init`.")
        raise typer.Exit()
    store = Store(db)
    traces = store.list_traces()
    n_events = sum(t.n_events for t in traces)
    proposals = store.list_proposals()
    by_status: dict[str, int] = {}
    for p in proposals:
        by_status[p.status] = by_status.get(p.status, 0) + 1
    active = sum(1 for e in store.list_entries() if store.active_version(e.id))
    typer.echo("LoopSmith status")
    kv("traces", f"{len(traces)} ({n_events} events)")
    kv("proposals", f"{len(proposals)} " + (
        ", ".join(f"{k}={v}" for k, v in sorted(by_status.items())) or "none"))
    kv("active entries", active)
    latest_audit = store.audit(limit=1)
    if latest_audit:
        kv("last event", f"{latest_audit[0].kind} at {latest_audit[0].ts:%Y-%m-%d %H:%M} UTC")


def main() -> None:
    app()
