"""Opaque pagination cursors (API spec section 3): base64url of the last row's sort key."""

import base64
import binascii
import json
from datetime import datetime


class BadCursor(ValueError):
    """The cursor wasn't one this API issued."""


def encode(sched_start: datetime, trip_id: str) -> str:
    raw = json.dumps([sched_start.isoformat(), trip_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(token: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        start, trip_id = json.loads(raw)
        when = datetime.fromisoformat(start)
    except (binascii.Error, ValueError, TypeError, UnicodeDecodeError) as exc:
        raise BadCursor("not a cursor from this API") from exc
    if not isinstance(trip_id, str) or not trip_id or when.tzinfo is None:
        raise BadCursor("not a cursor from this API")
    return when, trip_id
