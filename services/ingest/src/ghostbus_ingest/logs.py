"""Structured logs: one JSON line per event on stdout (infra spec, section 7)."""

import json
from datetime import UTC, datetime
from typing import Any


def log_event(event: str, **fields: Any) -> None:
    """Write one JSON line. Never pass credentials, secret URLs, or email addresses here."""
    record = {"ts": datetime.now(tz=UTC).isoformat(), "service": "ingest", "event": event}
    print(json.dumps(record | fields), flush=True)
