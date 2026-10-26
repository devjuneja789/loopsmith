"""SQLite persistence: stdlib sqlite3, JSON columns, nested transactions.

All writes go through `Store.tx()`, which flattens nesting (inner joins the
outer transaction) so multi-step transitions in `versioning` are atomic.
"""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loopsmith.core.models import (
    AuditEvent,
    Entry,
    EntryVersion,
    EvalRun,
    Evidence,
    Proposal,
)
from loopsmith.core.util import new_id, now_utc
from loopsmith.traces.schema import SessionMeta, Trace, TraceEvent

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS traces (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    project     TEXT NOT NULL,
    session_json TEXT NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trace_events (
    id           TEXT PRIMARY KEY,
    trace_id     TEXT NOT NULL REFERENCES traces(id),
    seq          INTEGER NOT NULL,
    ts           TEXT,
    kind         TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    raw_json     TEXT,
    UNIQUE (trace_id, seq)
);
CREATE TABLE IF NOT EXISTS entries (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (kind, name)
);
CREATE TABLE IF NOT EXISTS entry_versions (
    id         TEXT PRIMARY KEY,
    entry_id   TEXT NOT NULL REFERENCES entries(id),
    n          INTEGER NOT NULL,
    body_md    TEXT NOT NULL,
    rationale  TEXT,
    status     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (entry_id, n)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_per_entry
    ON entry_versions(entry_id) WHERE status = 'active';
CREATE TABLE IF NOT EXISTS proposals (
    id           TEXT PRIMARY KEY,
    op           TEXT NOT NULL,
    kind         TEXT NOT NULL,
    name         TEXT NOT NULL,
    target_n     INTEGER,
    body_md      TEXT NOT NULL,
    rationale    TEXT NOT NULL,
    origin       TEXT NOT NULL,
    status       TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_runs (
    id                  TEXT PRIMARY KEY,
    proposal_id         TEXT NOT NULL REFERENCES proposals(id),
    benchmark_id        TEXT NOT NULL,
    benchmark_hash     TEXT NOT NULL,
    model              TEXT,
    params_json        TEXT NOT NULL,
    baseline_pack_hash TEXT NOT NULL,
    candidate_pack_hash TEXT NOT NULL,
    verdict            TEXT NOT NULL,
    summary_json       TEXT NOT NULL,
    started_at         TEXT NOT NULL,
    finished_at        TEXT
);
CREATE TABLE IF NOT EXISTS eval_results (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES eval_runs(id),
    scenario_id     TEXT NOT NULL,
    arm             TEXT NOT NULL,
    run_ix          INTEGER NOT NULL,
    success         INTEGER NOT NULL,
    score           REAL,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    turns           INTEGER,
    wall_s          REAL,
    transcript_path TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
    id            TEXT PRIMARY KEY,
    ts            TEXT NOT NULL,
    kind          TEXT NOT NULL,
    payload_json  TEXT NOT NULL
);
"""


@dataclass
class TraceSummary:
    id: str
    source: str
    project: str
    imported_at: datetime
    n_events: int


class Store:
    def __init__(self, path: Path | str):
        path = Path(path)
        if path.parent and str(path.parent) not in ("", "."):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._in_tx = False
        self._init_schema()

    # -- lifecycle ---------------------------------------------------------

    def _init_schema(self) -> None:
        with self.tx():
            self._conn.executescript(SCHEMA_SQL)
            self._conn.execute(
                "INSERT OR IGNORE INTO audit_events (id, ts, kind, payload_json) "
                "VALUES (?, ?, 'db_initialized', ?)",
                (new_id("a"), now_utc().isoformat(), json.dumps({"schema_version": SCHEMA_VERSION})),
            )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def tx(self):
        """Nested transactions join the outer one; only the outer commits."""
        if self._in_tx:
            yield
            return
        self._in_tx = True
        try:
            yield
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        finally:
            self._in_tx = False

    def _row(self, sql: str, args: tuple) -> sqlite3.Row | None:
        return self._conn.execute(sql, args).fetchone()

    # -- traces ------------------------------------------------------------

    def save_trace(self, trace: Trace, events: list[TraceEvent]) -> None:
        with self.tx():
            self._conn.execute(
                "INSERT INTO traces (id, source, project, session_json, imported_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (trace.id, trace.source, trace.project,
                 trace.session.model_dump_json(), trace.imported_at.isoformat()),
            )
            self._conn.executemany(
                "INSERT INTO trace_events (id, trace_id, seq, ts, kind, payload_json, raw_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (new_id("e"), trace.id, ev.seq,
                     ev.ts.isoformat() if ev.ts else None, ev.kind,
                     ev.model_dump_json(include={"payload"}), json.dumps(ev.raw) if ev.raw else None)
                    for ev in events
                ],
            )
            self.log("imported", {"trace_id": trace.id, "source": trace.source,
                                 "project": trace.project, "events": len(events)})

    def trace_exists(self, trace_id: str) -> bool:
        return self._row("SELECT 1 FROM traces WHERE id = ?", (trace_id,)) is not None

    def list_traces(self, project: str | None = None) -> list[TraceSummary]:
        sql = (
            "SELECT t.id, t.source, t.project, t.imported_at, "
            "  (SELECT COUNT(*) FROM trace_events e WHERE e.trace_id = t.id) AS n_events "
            "FROM traces t"
        )
        args: tuple = ()
        if project:
            sql += " WHERE t.project = ?"
            args = (project,)
        sql += " ORDER BY t.imported_at"
        return [
            TraceSummary(
                id=row["id"], source=row["source"], project=row["project"],
                imported_at=datetime.fromisoformat(row["imported_at"]),
                n_events=row["n_events"],
            )
            for row in self._conn.execute(sql, args)
        ]

    def get_trace(self, trace_id: str) -> Trace | None:
        row = self._row("SELECT * FROM traces WHERE id = ?", (trace_id,))
        if not row:
            return None
        return Trace(
            id=row["id"], source=row["source"], project=row["project"],
            session=SessionMeta.model_validate_json(row["session_json"]),
            imported_at=datetime.fromisoformat(row["imported_at"]),
        )

    def trace_events(self, trace_id: str) -> list[TraceEvent]:
        rows = self._conn.execute(
            "SELECT seq, ts, kind, payload_json, raw_json FROM trace_events "
            "WHERE trace_id = ? ORDER BY seq", (trace_id,)
        )
        return [
            TraceEvent(
                seq=row["seq"],
                ts=datetime.fromisoformat(row["ts"]) if row["ts"] else None,
                kind=row["kind"],
                payload=json.loads(row["payload_json"])["payload"],
                raw=json.loads(row["raw_json"]) if row["raw_json"] else None,
            )
            for row in rows
        ]

    def all_events_by_trace(self, project: str | None = None) -> list[tuple[Trace, list[TraceEvent]]]:
        result: list[tuple[Trace, list[TraceEvent]]] = []
        for summary in self.list_traces(project=project):
            trace = self.get_trace(summary.id)
            if trace is not None:
                result.append((trace, self.trace_events(trace.id)))
        return result

    def event_exists(self, trace_id: str, seq: int) -> bool:
        return self._row(
            "SELECT 1 FROM trace_events WHERE trace_id = ? AND seq = ?",
            (trace_id, seq),
        ) is not None

    # -- entries & versions --------------------------------------------------

    def get_entry(self, kind: str, name: str) -> Entry | None:
        row = self._row("SELECT * FROM entries WHERE kind = ? AND name = ?", (kind, name))
        return self._entry_from_row(row) if row else None

    def find_entry_by_name(self, name: str) -> Entry | None:
        row = self._row("SELECT * FROM entries WHERE name = ?", (name,))
        return self._entry_from_row(row) if row else None

    def list_entries(self, kind: str | None = None) -> list[Entry]:
        if kind:
            rows = self._conn.execute(
                "SELECT * FROM entries WHERE kind = ? ORDER BY kind, name", (kind,))
        else:
            rows = self._conn.execute("SELECT * FROM entries ORDER BY kind, name")
        return [self._entry_from_row(r) for r in rows]

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> Entry:
        return Entry(
            id=row["id"], kind=row["kind"], name=row["name"],
            description=row["description"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def create_entry(self, kind: str, name: str, description: str | None) -> Entry:
        entry = Entry(id=new_id("e"), kind=kind, name=name,
                      description=description, created_at=now_utc())
        with self.tx():
            self._conn.execute(
                "INSERT INTO entries (id, kind, name, description, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (entry.id, entry.kind, entry.name, entry.description,
                 entry.created_at.isoformat()),
            )
        return entry

    def add_version(self, entry_id: str, body_md: str, rationale: str | None,
                    status: str) -> EntryVersion:
        with self.tx():
            row = self._row(
                "SELECT COALESCE(MAX(n), 0) + 1 AS n FROM entry_versions WHERE entry_id = ?",
                (entry_id,))
            version = EntryVersion(
                id=new_id("v"), entry_id=entry_id, n=row["n"], body_md=body_md,
                rationale=rationale, status=status, created_at=now_utc())  # type: ignore[arg-type]
            self._conn.execute(
                "INSERT INTO entry_versions (id, entry_id, n, body_md, rationale, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (version.id, version.entry_id, version.n, version.body_md,
                 version.rationale, version.status, version.created_at.isoformat()),
            )
        return version

    def versions(self, entry_id: str) -> list[EntryVersion]:
        rows = self._conn.execute(
            "SELECT * FROM entry_versions WHERE entry_id = ? ORDER BY n", (entry_id,))
        return [
            EntryVersion(
                id=r["id"], entry_id=r["entry_id"], n=r["n"], body_md=r["body_md"],
                rationale=r["rationale"], status=r["status"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    def get_version(self, version_id: str) -> EntryVersion | None:
        row = self._row("SELECT * FROM entry_versions WHERE id = ?", (version_id,))
        if not row:
            return None
        return EntryVersion(
            id=row["id"], entry_id=row["entry_id"], n=row["n"], body_md=row["body_md"],
            rationale=row["rationale"], status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def active_version(self, entry_id: str) -> EntryVersion | None:
        row = self._row(
            "SELECT id FROM entry_versions WHERE entry_id = ? AND status = 'active'",
            (entry_id,))
        return self.get_version(row["id"]) if row else None

    def set_version_status(self, version_id: str, status: str) -> None:
        with self.tx():
            self._conn.execute(
                "UPDATE entry_versions SET status = ? WHERE id = ?", (status, version_id))

    # -- proposals -----------------------------------------------------------

    def add_proposal(self, proposal: Proposal) -> None:
        with self.tx():
            self._conn.execute(
                "INSERT INTO proposals (id, op, kind, name, target_n, body_md, rationale, "
                "origin, status, evidence_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (proposal.id, proposal.op, proposal.kind, proposal.name, proposal.target_n,
                 proposal.body_md, proposal.rationale, proposal.origin, proposal.status,
                 json.dumps([e.model_dump(mode="json") for e in proposal.evidence]),
                 proposal.created_at.isoformat()),
            )

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        row = self._row("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        if not row:
            return None
        return Proposal(
            id=row["id"], op=row["op"], kind=row["kind"], name=row["name"],
            target_n=row["target_n"], body_md=row["body_md"], rationale=row["rationale"],
            origin=row["origin"], status=row["status"],
            evidence=[Evidence.model_validate(e) for e in json.loads(row["evidence_json"])],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_proposals(self, status: str | None = None) -> list[Proposal]:
        if status:
            rows = self._conn.execute(
                "SELECT id FROM proposals WHERE status = ? ORDER BY created_at", (status,))
        else:
            rows = self._conn.execute("SELECT id FROM proposals ORDER BY created_at")
        ids = [r["id"] for r in rows]
        return [p for p in (self.get_proposal(pid) for pid in ids) if p is not None]

    def set_proposal_status(self, proposal_id: str, status: str) -> None:
        with self.tx():
            self._conn.execute(
                "UPDATE proposals SET status = ? WHERE id = ?", (status, proposal_id))

    # -- eval ----------------------------------------------------------------

    def add_eval_run(self, run: EvalRun) -> None:
        with self.tx():
            self._conn.execute(
                "INSERT INTO eval_runs (id, proposal_id, benchmark_id, benchmark_hash, model, "
                "params_json, baseline_pack_hash, candidate_pack_hash, verdict, summary_json, "
                "started_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run.id, run.proposal_id, run.benchmark_id, run.benchmark_hash, run.model,
                 json.dumps(run.params), run.baseline_pack_hash, run.candidate_pack_hash,
                 run.verdict, json.dumps(run.summary), run.started_at.isoformat(),
                 run.finished_at.isoformat() if run.finished_at else None),
            )

    def update_eval_run(self, run: EvalRun) -> None:
        with self.tx():
            self._conn.execute(
                "UPDATE eval_runs SET verdict = ?, summary_json = ?, finished_at = ? WHERE id = ?",
                (run.verdict, json.dumps(run.summary),
                 run.finished_at.isoformat() if run.finished_at else None, run.id),
            )

    def eval_runs_for(self, proposal_id: str) -> list[EvalRun]:
        rows = self._conn.execute(
            "SELECT * FROM eval_runs WHERE proposal_id = ? ORDER BY started_at", (proposal_id,))
        return [
            EvalRun(
                id=r["id"], proposal_id=r["proposal_id"], benchmark_id=r["benchmark_id"],
                benchmark_hash=r["benchmark_hash"], model=r["model"],
                params=json.loads(r["params_json"]), baseline_pack_hash=r["baseline_pack_hash"],
                candidate_pack_hash=r["candidate_pack_hash"], verdict=r["verdict"],
                summary=json.loads(r["summary_json"]),
                started_at=datetime.fromisoformat(r["started_at"]),
                finished_at=datetime.fromisoformat(r["finished_at"]) if r["finished_at"] else None,
            )
            for r in rows
        ]

    # -- audit ---------------------------------------------------------------

    def log(self, kind: str, payload: dict) -> None:
        with self.tx():
            self._conn.execute(
                "INSERT INTO audit_events (id, ts, kind, payload_json) VALUES (?, ?, ?, ?)",
                (new_id("a"), now_utc().isoformat(), kind, json.dumps(payload)),
            )

    def audit(self, limit: int = 50) -> list[AuditEvent]:
        rows = self._conn.execute(
            "SELECT * FROM audit_events ORDER BY ts DESC, rowid DESC LIMIT ?", (limit,))
        return [
            AuditEvent(
                id=r["id"], ts=datetime.fromisoformat(r["ts"]), kind=r["kind"],
                payload=json.loads(r["payload_json"]),
            )
            for r in rows
        ]
