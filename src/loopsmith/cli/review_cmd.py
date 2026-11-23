"""Review explicit command corrections in a single selected session."""

import re
from pathlib import Path

import typer

from loopsmith import paths
from loopsmith.cli import proposals_cmd
from loopsmith.core.models import Evidence, Proposal
from loopsmith.core.store import Store
from loopsmith.core.util import content_id, now_utc
from loopsmith.eval import gates
from loopsmith.mining.heuristics import slugify
from loopsmith.traces import importers


def corrections(events):
    """Require a positive command preference and a matching completed invocation."""
    for index, event in enumerate(events):
        if event.kind != "user.message":
            continue
        message = str(event.payload.get("text", "")).strip()
        if len(message) > 600 or "\n" in message:
            continue
        match = re.search(r"\b(?:use|prefer|run)\s+`([^`\n]+)`", message, re.I)
        if not match or re.search(r"(?:don't|do not|never|avoid)\s*$", message[:match.start()], re.I):
            continue
        if not re.search(r"\b(?:instead|wrong|prefer|always|in this (?:repo|project)|not raw)\b", message, re.I):
            continue
        cmd = match[1]
        call = None
        for following in events[index + 1:]:
            if following.kind == "user.message":
                break
            if following.payload.get("command") != cmd:
                continue
            if following.kind == "tool.call":
                call = following
            elif following.kind == "test.run" and following.payload.get("exit_code") == 0 and following.payload.get("failed") == 0:
                yield message, cmd, [event.seq, following.seq]
                break
            elif (following.kind == "tool.result" and call and following.payload.get("call_id")
                  == call.payload.get("call_id") and following.payload.get("exit_code") == 0):
                yield message, cmd, [event.seq, call.seq, following.seq]
                break


def review(session: Path = typer.Option(..., "--session", exists=True, dir_okay=False, readable=True)):
    """Review one local session and show evidence and proposed instruction edits."""
    db = paths.db_path()
    if db == Path(".loopsmith/loopsmith.db"):
        db.parent.mkdir(exist_ok=True)
        ignore = db.parent / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8")
    store = Store(db)
    try:
        result = importers.ingest(store, session, Path.cwd().name)
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc), param_hint="--session") from exc
    events = store.trace_events(result.trace_id)
    target = Path("AGENTS.md")
    existing = target.read_text(encoding="utf-8-sig") if target.exists() else ""
    found = False
    for message, cmd, refs in corrections(events):
        if message in existing:
            continue
        name = "use-" + slugify(cmd)[:44]
        entry = store.get_entry("instruction", name)
        active = store.active_version(entry.id) if entry else None
        if active and active.body_md.strip() == message:
            continue
        target_n = active.n if active else None
        pid = content_id("p", "review", result.trace_id, str(refs), message, str(target_n))
        proposal = store.get_proposal(pid)
        if proposal is None:
            proposal = Proposal(id=pid, op="update" if active else "create",
                                target_n=target_n, kind="instruction", name=name, body_md=message,
                                rationale=f"User named a preferred command; `{cmd}` subsequently succeeded.",
                                evidence=[Evidence(trace_id=result.trace_id, event_refs=refs,
                                                   pattern="user_correction", excerpt=message)],
                                origin="heuristic", created_at=now_utc())
            store.add_proposal(proposal)
        if proposal.status not in ("pending", "evaluated"):
            continue
        if not store.eval_runs_for(pid):
            gates.evaluate(store, pid)
        found = True
        proposals_cmd.show(pid)
        proposals_cmd.diff(pid)
        report = gates.static_gates(store, proposal)
        typer.echo("Static checks passed." if report.passed else
                   "Static checks failed: " + ", ".join(c.reason for c in report.failures()))
        typer.echo("Review ran locally. No behavioral evaluation was run by this command.")
    if not found:
        typer.echo("No new reusable command correction found in this session.")
