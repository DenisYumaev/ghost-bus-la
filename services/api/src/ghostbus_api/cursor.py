"""Opaque pagination cursors (API spec section 3): base64url of the query the page belongs to
(line, service date) and the last row's sort key. A cursor reused with another line or date is
refused rather than silently restarting or emptying the list."""

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import date, datetime


class BadCursor(ValueError):
    """The cursor wasn't one this API issued for this query."""


@dataclass(frozen=True)
class Position:
    line: str
    service_date: date
    sched_start: datetime
    trip_id: str


def encode(pos: Position) -> str:
    raw = json.dumps(
        [pos.line, pos.service_date.isoformat(), pos.sched_start.isoformat(), pos.trip_id],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(token: str) -> Position:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        line, day, start, trip_id = json.loads(raw)
        pos = Position(line, date.fromisoformat(day), datetime.fromisoformat(start), trip_id)
    except (binascii.Error, ValueError, TypeError, UnicodeDecodeError) as exc:
        raise BadCursor("not a cursor from this API") from exc
    if not all(isinstance(v, str) and v for v in (pos.line, pos.trip_id)):
        raise BadCursor("not a cursor from this API")
    if pos.sched_start.tzinfo is None:
        raise BadCursor("not a cursor from this API")
    return pos
