"""`loopsmith proposals` subcommands: list / show / diff / reject."""

import difflib
import json
from typing import Optional

import typer

from loopsmith import paths
from loopsmith.cli.out import print_table

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command("list")
def list_(
    status: Optional[str] = typer.Option(None, "--status", "-s",
                                         help="pending | evaluated | approved | rejected | stale"),
    format: str = typer.Option("table", "--format", "-f",
                               help="table | json | ids"),
) -> None:
    """List refinement proposals."""
    from loopsmith.core.store import Store

    store = Store(paths.db_path())
    proposals = store.list_proposals(status=status)
    if format == "ids":
        for p in proposals:
            typer.echo(p.id)
        return
    if format == "json":
        typer.echo(json.dumps(
            [{"id": p.id, "op": p.op, "kind": p.kind, "name": p.name,
              "status": p.status, "origin": p.origin, "target_n": p.target_n,
              "evidence": len(p.evidence)} for p in proposals], indent=2))
        return
    print_table(
        ["id", "op", "kind", "name", "status", "origin", "evidence"],
        [[p.id, p.op, p.kind, p.name, p.status, p.origin, len(p.evidence)]
         for p in proposals],
    )


@app.command()
def show(proposal_id: str = typer.Argument(..., help="Proposal id")) -> None:
    """Show a proposal in full: rationale, body, and trace evidence."""
    from loopsmith.core.store import Store

    store = Store(paths.db_path())
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        typer.echo(f"error: no proposal {proposal_id}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Proposal {proposal.id}")
    typer.echo(f"  {proposal.op} {proposal.kind}/{proposal.name}"
               + (f" (targets v{proposal.target_n})" if proposal.target_n else ""))
    typer.echo(f"  status:  {proposal.status}   origin: {proposal.origin}")
    typer.echo(f"  rationale: {proposal.rationale}")
    typer.echo("")
    typer.echo("-- proposed body " + "-" * 40)
    typer.echo(proposal.body_md.strip())
    typer.echo("-- evidence " + "-" * 47)
    print_table(
        ["trace", "events", "pattern", "excerpt"],
        [[e.trace_id, ",".join(str(r) for r in e.event_refs), e.pattern, e.excerpt]
         for e in proposal.evidence],
    )
    runs = store.eval_runs_for(proposal.id)
    if runs:
        latest = runs[-1]
        typer.echo(f"-- latest eval: {latest.verdict} "
                   f"(model: {latest.model or 'n/a'})")


@app.command()
def diff(proposal_id: str = typer.Argument(..., help="Proposal id")) -> None:
    """Unified diff: active body vs proposed body."""
    from loopsmith.core.store import Store

    store = Store(paths.db_path())
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        typer.echo(f"error: no proposal {proposal_id}", err=True)
        raise typer.Exit(1)
    entry = store.get_entry(proposal.kind, proposal.name)
    active = store.active_version(entry.id) if entry else None
    old = (active.body_md if active else "").splitlines()
    from_label = f"active v{active.n}" if active else "(new entry)"
    new = proposal.body_md.splitlines()
    typer.echo(f"diff -- {proposal.kind}/{proposal.name} ({from_label} -> proposed)")
    typer.echo("\n".join(difflib.unified_diff(
        old, new, fromfile=from_label, tofile="proposed", lineterm="")))


@app.command()
def reject(
    proposal_id: str = typer.Argument(..., help="Proposal id"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation"),
) -> None:
    """Reject a proposal (recorded; nothing is deleted)."""
    from loopsmith.core.store import Store

    store = Store(paths.db_path())
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        typer.echo(f"error: no proposal {proposal_id}", err=True)
        raise typer.Exit(1)
    if proposal.status not in ("pending", "evaluated"):
        typer.echo(f"error: proposal is {proposal.status}", err=True)
        raise typer.Exit(1)
    if not yes and not typer.confirm(f"Reject {proposal.kind}/{proposal.name}?"):
        raise typer.Exit(1)
    store.set_proposal_status(proposal.id, "rejected")
    store.log("rejected", {"proposal_id": proposal.id, "kind": proposal.kind,
                          "name": proposal.name})
    typer.echo(f"Rejected {proposal.id} ({proposal.kind}/{proposal.name}).")
