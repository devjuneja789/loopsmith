"""Small shared utilities: IDs and timestamps."""

import hashlib
import uuid
from datetime import datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Random short id, e.g. 'v1a2b3c4d5e6f'."""
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def content_id(prefix: str, *parts: str) -> str:
    """Deterministic id from content, so re-mining is idempotent."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}{digest}"


def sha256_short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
