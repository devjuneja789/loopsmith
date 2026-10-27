"""Filesystem layout helpers (env-overridable)."""

import os
from pathlib import Path

DB_ENV = "LOOPSMITH_DB"
PROJECT_ENV = "LOOPSMITH_PROJECT"
EXPORT_ENV = "LOOPSMITH_EXPORT_DIR"


def db_path() -> Path:
    override = os.environ.get(DB_ENV)
    if override:
        return Path(override).expanduser()
    return Path(".loopsmith") / "loopsmith.db"


def default_project() -> str:
    return os.environ.get(PROJECT_ENV, "default")


def default_export_dir() -> Path:
    override = os.environ.get(EXPORT_ENV)
    return Path(override) if override else Path("dist")


def runs_dir() -> Path:
    """Where behavioral eval transcripts are stored."""
    return db_path().parent / "runs"
