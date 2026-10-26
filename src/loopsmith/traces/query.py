"""Typed accessors over canonical trace events (payloads are free-form)."""

from loopsmith.traces.schema import TraceEvent


def text(ev: TraceEvent) -> str:
    value = ev.payload.get("text", "")
    return str(value) if value is not None else ""


def command(ev: TraceEvent) -> str:
    """Command identity for grouping: test command, tool name + args."""
    if "command" in ev.payload and ev.payload["command"]:
        return str(ev.payload["command"])
    if "name" in ev.payload:
        name = str(ev.payload["name"])
        args = ev.payload.get("args", "")
        return f"{name} {args}".strip()
    return ""


def norm_command(cmd: str) -> str:
    """First two whitespace-collapsed, lowercased tokens ('make test -k x' → 'make test')."""
    parts = cmd.split()
    return " ".join(parts[:2]).lower() if parts else ""


def ok(ev: TraceEvent) -> bool:
    if ev.kind == "test.run":
        return ev.payload.get("failed", 1) == 0 and ev.payload.get("exit_code", 1) == 0
    if ev.kind in ("tool.call", "tool.result"):
        if "ok" in ev.payload:
            return bool(ev.payload["ok"])
        return ev.payload.get("exit_code", 0) == 0
    return True


def excerpt(text: str, limit: int = 140) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def summarize(ev: TraceEvent) -> str:
    """One-line human summary for tables."""
    if ev.kind in ("user.message", "assistant.message"):
        return excerpt(text(ev))
    if ev.kind == "test.run":
        passed, failed, exit_code = ev.payload.get("passed", 0), ev.payload.get("failed", 0), ev.payload.get("exit_code", 0)
        return f"{command(ev)} -> {passed} passed, {failed} failed (exit {exit_code})"
    if ev.kind in ("tool.call", "tool.result"):
        return f"{command(ev)} -> {'ok' if ok(ev) else 'failed'}"
    if ev.kind == "file.edit":
        return str(ev.payload.get("path", ""))
    if ev.kind == "turn.outcome":
        return f"{ev.payload.get('status', '')}: {excerpt(str(ev.payload.get('note', '')))}"
    return ""
