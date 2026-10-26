"""Domain models: entries, versions, proposals, evidence, eval runs, audit.

Design notes:
- An `Entry` is the registry row for one piece of harness state (a memory,
  skill, or project instruction). Its content lives in immutable
  `EntryVersion` rows; "active" is a pointer, so rollback never deletes.
- A `Proposal` is the smallest evidence-cited CRUD edit (create/update)
  mined from traces. Nothing becomes active without human approval.
- `EvalRun` records gate results; `verdict` "not_run" means behavioral
  evaluation was skipped (no model configured) and approval requires an
  explicit, recorded override.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EntryKind = Literal["memory", "skill", "instruction"]
ProposalStatus = Literal["pending", "evaluated", "approved", "rejected", "stale"]
VersionStatus = Literal["candidate", "active", "superseded", "reverted"]
Verdict = Literal["promote", "reject", "inconclusive", "not_run"]


class Entry(BaseModel):
    id: str
    kind: EntryKind
    name: str
    description: str | None = None
    created_at: datetime


class EntryVersion(BaseModel):
    id: str
    entry_id: str
    n: int
    body_md: str
    rationale: str | None = None
    status: VersionStatus
    created_at: datetime


class Evidence(BaseModel):
    """A citation into imported trace events. Refs must resolve in the DB."""

    trace_id: str
    event_refs: list[int] = Field(default_factory=list)
    pattern: str
    excerpt: str = ""


class Proposal(BaseModel):
    id: str
    op: Literal["create", "update"]
    kind: EntryKind
    name: str
    target_n: int | None = None
    body_md: str
    rationale: str
    origin: Literal["heuristic", "llm"]
    status: ProposalStatus = "pending"
    evidence: list[Evidence] = Field(default_factory=list)
    created_at: datetime


class EvalRun(BaseModel):
    id: str
    proposal_id: str
    benchmark_id: str = "static-only"
    benchmark_hash: str = "0"
    model: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    baseline_pack_hash: str = ""
    candidate_pack_hash: str = ""
    verdict: Verdict
    summary: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime | None = None


class AuditEvent(BaseModel):
    id: str
    ts: datetime
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
