"""`loopsmith export` -- render the approved pack as Markdown."""

from pathlib import Path
from typing import Optional

import typer

from loopsmith import paths
from loopsmith.core.store import Store


def export(
    out: Optional[Path] = typer.Option(None, "--out", "-o",
                                       help="Export directory (default: dist/)"),
    format: str = typer.Option("all", "--format", "-f",
                                help="agents | memory | skills | pack | all"),
) -> None:
    """Export active entries as AGENTS.md / MEMORY.md / SKILL.md / pack."""
    from loopsmith.export import render

    store = Store(paths.db_path())
    out_dir = out or paths.default_export_dir()
    written = render.export_all(store, out_dir, which=format)
    if not written:
        typer.echo("Nothing to export -- approve a proposal first.")
        return
    typer.echo(f"Exported {len(written)} file(s) to {out_dir}/:")
    for path in written:
        typer.echo(f"  {path}")
