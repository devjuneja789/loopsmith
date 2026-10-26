"""Canonical LoopSmith trace schema.

Every imported trace is normalized to this shape regardless of source
format. `raw` preserves the original event for provenance so adapters
never lose information.

Payload shapes by kind:
    user.message / assistant.message:
        {"text": str}
    tool.call / tool.result:
        {"name": str, "args"?: str, "command"?: str, "ok"?: bool,
         "exit_code"?: int, "duration_ms"?: int}
    file.edit:
        {"path": str, "patch_present": bool}
    test.run:
        {"framework": str, "command": str, "passed": int, "failed": int,
         "exit_code": int, "duration_ms"?: int}
    turn.outcome:
        {"status": "success" | "failure" | "retry" | "user_correction",
         "note"?: str}
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

EventKind = Literal[
    "user.message",
    "assistant.message",
    "tool.call",
    "tool.result",
    "file.edit",
    "test.run",
    "turn.outcome",
]

KNOWN_EVENT_KINDS: frozenset[str] = frozenset(
    ["user.message", "assistant.message", "tool.call", "tool.result",
     "file.edit", "test.run", "turn.outcome"]
)


class SessionMeta(BaseModel):
    agent: str | None = None
    model: str | None = None
    cwd: str | None = None
    started_at: datetime | None = None


class TraceEvent(BaseModel):
    seq: int = Field(..., ge=1)
    ts: datetime | None = None
    kind: EventKind
    payload: dict[str, object] = Field(default_factory=dict)
    raw: dict[str, object] | None = None


class Trace(BaseModel):
    id: str
    source: str
    project: str
    session: SessionMeta = Field(default_factory=SessionMeta)
    imported_at: datetime
