"""`loopsmith traces` subcommands."""

import typer

from loopsmith import paths
from loopsmith.cli.out import kv, print_table
from loopsmith.traces import query as q

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command("list")
def list_(
    project: str = typer.Option(None, "--project", "-p", help="Filter by project"),
) -> None:
    """List imported traces."""
    from loopsmith.core.store import Store

    store = Store(paths.db_path())
    rows = [[t.id, t.project, t.source, t.n_events, f"{t.imported_at:%Y-%m-%d %H:%M}"]
            for t in store.list_traces(project=project)]
    print_table(["trace", "project", "source", "events", "imported"], rows)


@app.command()
def show(trace_id: str = typer.Argument(..., help="Trace id (from `traces list`)")) -> None:
    """Show a trace's session metadata and event stream."""
    from loopsmith.core.store import Store

    store = Store(paths.db_path())
    trace = store.get_trace(trace_id)
    if trace is None:
        typer.echo(f"error: no trace {trace_id}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Trace {trace.id}")
    kv("source", trace.source)
    kv("project", trace.project)
    kv("agent", trace.session.agent or "?")
    kv("model", trace.session.model or "?")
    kv("cwd", trace.session.cwd or "?")
    typer.echo("")
    events = store.trace_events(trace_id)
    print_table(
        ["seq", "kind", "summary"],
        [[e.seq, e.kind, q.summarize(e)] for e in events],
    )
