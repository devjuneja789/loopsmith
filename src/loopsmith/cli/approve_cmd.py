"""Approval, rollback, and history commands -- the human gate."""

from typing import Optional

import typer

from loopsmith import paths
from loopsmith.cli.out import print_table
from loopsmith.core.store import Store


def approve(
    proposal_id: str = typer.Argument(..., help="Proposal id"),
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt"),
    force: bool = typer.Option(False, "--force",
                               help="Override a not-run/inconclusive verdict "
                                    "(recorded in the audit log)"),
) -> None:
    """Promote a proposal into the next active version (human gate)."""
    from loopsmith.core import versioning

    store = Store(paths.db_path())
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        typer.echo(f"error: no proposal {proposal_id}", err=True)
        raise typer.Exit(1)
    if proposal.status not in ("pending", "evaluated"):
        typer.echo(f"error: proposal is {proposal.status}", err=True)
        raise typer.Exit(1)

    runs = store.eval_runs_for(proposal_id)
    latest = runs[-1] if runs else None
    if latest is not None and latest.verdict == "reject":
        typer.echo("refused: latest eval verdict is reject "
                   "(static gates failed). Re-mine or write a new proposal.",
                   err=True)
        raise typer.Exit(1)
    if latest is None and not force:
        typer.echo(f"refused: no eval yet -- run `loopsmith eval {proposal_id}` "
                   "first (or pass --force).", err=True)
        raise typer.Exit(1)
    if latest is not None and latest.verdict != "promote" and not force:
        typer.echo(f"refused: latest verdict is {latest.verdict}; promotion "
                   "requires verdict promote or --force.", err=True)
        raise typer.Exit(1)
    if not yes and not typer.confirm(
            f"Promote {proposal.kind}/{proposal.name} ({proposal.op}) to active?"):
        raise typer.Exit(1)
    try:
        version = versioning.promote(store, proposal, forced=force)
    except versioning.VersioningError as exc:
        typer.echo(f"refused: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Promoted {proposal.kind}/{proposal.name} -> v{version.n} (active).")
    typer.echo("Version history preserved; rollback with "
               f"`loopsmith rollback {proposal.kind} {proposal.name}`.")
    typer.echo("Export with `loopsmith export`.")


def rollback(
    kind: str = typer.Argument(..., help="memory | skill | instruction"),
    name: str = typer.Argument(..., help="Entry name"),
    to: Optional[int] = typer.Option(None, "--to", help="Version number "
                                   "(default: the previous version)"),
) -> None:
    """Roll an entry back to an earlier version (pointer move; history kept)."""
    from loopsmith.core import versioning

    store = Store(paths.db_path())
    try:
        target = versioning.rollback(store, kind, name, to_n=to)
    except versioning.VersioningError as exc:
        typer.echo(f"refused: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Rolled back {kind}/{name} -> v{target.n} (active). "
               "Later versions are marked reverted, not deleted.")


def history(
    kind: str = typer.Argument(..., help="memory | skill | instruction"),
    name: str = typer.Argument(..., help="Entry name"),
) -> None:
    """Show the version timeline of an entry."""
    store = Store(paths.db_path())
    entry = store.get_entry(kind, name)
    if entry is None:
        typer.echo(f"error: no entry {kind}/{name}", err=True)
        raise typer.Exit(1)
    versions = store.versions(entry.id)
    if not versions:
        typer.echo(f"{kind}/{name} has no versions.")
        return
    typer.echo(f"History of {kind}/{name}"
               + (f" -- {entry.description}" if entry.description else ""))
    print_table(
        ["v", "status", "created (UTC)", "rationale"],
        [[v.n, v.status, f"{v.created_at:%Y-%m-%d %H:%M}", v.rationale or ""]
         for v in versions],
    )
