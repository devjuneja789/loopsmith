"""Duration parsing helpers for acme-api."""

_UNITS = {"s": 1, "m": 60, "h": 3600}


def parse_duration(text: str) -> int:
    """Parse a single-unit duration such as "90m" or "2h" into seconds."""
    if not text or text[-1] not in _UNITS:
        raise ValueError(f"bad duration: {text!r}")
    return int(text[:-1])