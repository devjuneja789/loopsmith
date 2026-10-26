"""Trace importers: normalize foreign session logs into canonical traces.

Formats:
- `loopsmith` (canonical JSONL): one event per line, optional first line
  {"kind": "session", ...} for session metadata. This is the format
  examples/ and tests use.
- `generic-jsonl`: lenient OpenAI-messages-style logs ({"role", "content",
  optional "tool_calls"}); mapped best-effort with `raw` preserved.
- `auto`: sniff the first non-empty lines.

Trace ids are content hashes, so re-importing a file is a no-op.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loopsmith.core.store import Store
from loopsmith.core.util import now_utc
from loopsmith.traces.schema import (
    KNOWN_EVENT_KINDS,
    EventKind,
    SessionMeta,
    Trace,
    TraceEvent,
)

SOURCE_LOOPSMITH = "loopsmith-jsonl"
SOURCE_GENERIC = "generic-jsonl"
FORMATS = ("auto", "loopsmith", "generic")


class ImportFormatError(ValueError):
    pass


@dataclass
class ParsedTrace:
    trace: Trace
    events: list[TraceEvent]
    skipped: int = 0


@dataclass
class ImportResult:
    trace_id: str
    source: str
    project: str
    events: int = 0
    skipped: int = 0
    duplicate: bool = False


def _parse_ts(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_json_line(line: str, path: Path, lineno: int) -> dict:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ImportFormatError(f"{path}:{lineno}: invalid JSON ({exc})") from exc
    if not isinstance(obj, dict):
        raise ImportFormatError(f"{path}:{lineno}: expected a JSON object")
    return obj


def sniff_format(path: Path) -> str:
    for lineno, line in enumerate(_read_lines(path)[:5], start=1):
        obj = json.loads(line)  # _read_lines already validated? not yet: let it raise
        if not isinstance(obj, dict):
            continue
        if obj.get("kind") in KNOWN_EVENT_KINDS or obj.get("kind") == "session":
            return "loopsmith"
        if "role" in obj:
            return "generic"
    raise ImportFormatError(f"{path}: unrecognized trace format (no 'kind' or 'role' lines)")


def parse_file(path: Path, project: str, fmt: str = "auto") -> ParsedTrace:
    if fmt == "auto":
        fmt = sniff_format(path)
    elif fmt not in ("loopsmith", "generic"):
        raise ImportFormatError(f"unknown format '{fmt}' (use one of {FORMATS})")
    trace_id = "t" + hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    if fmt == "loopsmith":
        session, events, skipped = _parse_canonical(path)
        source = SOURCE_LOOPSMITH
    else:
        session, events, skipped = _parse_generic(path)
        source = SOURCE_GENERIC
    trace = Trace(id=trace_id, source=source, project=project,
                  session=session, imported_at=now_utc())
    return ParsedTrace(trace=trace, events=events, skipped=skipped)


def _parse_canonical(path: Path) -> tuple[SessionMeta, list[TraceEvent], int]:
    session = SessionMeta()
    events: list[TraceEvent] = []
    skipped = 0
    seen_seqs: set[int] = set()
    auto_seq = 0
    for lineno, line in enumerate(_read_lines(path), start=1):
        obj = _parse_json_line(line, path, lineno)
        kind = obj.get("kind")
        if kind == "session":
            session = SessionMeta(
                agent=obj.get("agent"), model=obj.get("model"), cwd=obj.get("cwd"),
                started_at=_parse_ts(obj.get("started_at")),
            )
            continue
        if kind not in KNOWN_EVENT_KINDS:
            skipped += 1
            continue
        if "seq" in obj and obj["seq"] is not None:
            seq = int(obj["seq"])
            if seq in seen_seqs:
                raise ImportFormatError(f"{path}:{lineno}: duplicate seq {seq}")
            seen_seqs.add(seq)
        else:
            auto_seq += 1
            seq = auto_seq
        payload = obj.get("payload")
        if payload is None:
            payload = {k: v for k, v in obj.items()
                       if k not in ("kind", "seq", "ts", "payload", "raw")}
        if not isinstance(payload, dict):
            raise ImportFormatError(f"{path}:{lineno}: payload must be an object")
        events.append(TraceEvent(
            seq=seq, ts=_parse_ts(obj.get("ts")), kind=kind,  # type: ignore[arg-type]
            payload=payload, raw=obj.get("raw"),
        ))
    # fill gaps if explicit seqs were used: renumber deterministically
    if seen_seqs:
        events.sort(key=lambda e: e.seq)
        events = [TraceEvent(seq=i, ts=e.ts, kind=e.kind, payload=e.payload, raw=e.raw)
                  for i, e in enumerate(events, start=1)]
    return session, events, skipped


def _parse_generic(path: Path) -> tuple[SessionMeta, list[TraceEvent], int]:
    session = SessionMeta()
    events: list[TraceEvent] = []
    skipped = 0
    seq = 0

    def emit(kind: EventKind, payload: dict, raw: dict) -> None:
        nonlocal seq
        seq += 1
        events.append(TraceEvent(seq=seq, kind=kind, payload=payload, raw=raw))

    for lineno, line in enumerate(_read_lines(path), start=1):
        obj = _parse_json_line(line, path, lineno)
        role = obj.get("role")
        if role == "system":
            skipped += 1
            continue
        content = obj.get("content") or ""
        if role == "user":
            emit("user.message", {"text": str(content)}, obj)
        elif role == "assistant":
            if content:
                emit("assistant.message", {"text": str(content)}, obj)
            for tc in obj.get("tool_calls") or []:
                function = (tc or {}).get("function") or {}
                args = function.get("arguments")
                emit("tool.call", {
                    "name": str(function.get("name", "")),
                    "args": str(args) if args else "",
                }, obj)
        elif role == "tool":
            emit("tool.result", {"output": str(content)}, obj)
        elif obj.get("type") in ("tool_use", "tool_result"):
            kind = "tool.call" if obj["type"] == "tool_use" else "tool.result"
            emit(kind, {"name": str(obj.get("name", "")),
                        "args": str(obj.get("input", ""))}, obj)
        else:
            skipped += 1
    return session, events, skipped


def ingest(store: Store, path: Path | str, project: str, fmt: str = "auto") -> ImportResult:
    """Parse and persist; content-hash ids make re-imports no-ops."""
    path = Path(path)
    parsed = parse_file(path, project, fmt)
    result = ImportResult(
        trace_id=parsed.trace.id, source=parsed.trace.source, project=project,
        events=len(parsed.events), skipped=parsed.skipped,
    )
    if store.trace_exists(parsed.trace.id):
        result.duplicate = True
        return result
    store.save_trace(parsed.trace, parsed.events)
    return result
