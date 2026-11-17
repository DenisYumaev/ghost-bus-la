"""Decode one WebSocket frame into typed rows (pipeline spec, section 3).

Metro's frames are GTFS-realtime entities as JSON, one per vehicle or trip. This is the one
tested place where they're parsed and validated:

- Types are strict: an integer must be a JSON integer (not `0.5`, not `true`), a coordinate
  a finite number in range, a timestamp an epoch-seconds integer or digit string, a start
  date `YYYYMMDD`. Anything else quarantines the frame with a reason naming the field
  (`bad:vehicle.position.latitude`), and the raw bytes are kept. Nothing is dropped.
- Unknown extra fields are tolerated (Metro may add some) and show up in the snapshot's
  schema fingerprint instead, which is what the schema-drift alert watches.
- Decoding never raises: any input gives rows or a `Quarantined`.

Times stay as received apart from typing: `start_time` is text, because it can pass 24:00.
"""

import hashlib
import json
import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ghostbus_core.service_date import parse_service_date

Row = dict[str, Any]


@dataclass(frozen=True)
class Quarantined:
    reason: str
    raw: bytes


class _Bad(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _load(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):  # JSONDecodeError and UnicodeDecodeError
        raise _Bad("not_json") from None
    if not isinstance(value, dict):
        raise _Bad("not_object")
    return value


def _at(obj: Any, path: str, kind: str, required: bool = False, label: str | None = None) -> Any:
    """The value at a dotted path, checked against `kind`; None if absent and optional."""
    name = label or path
    value = obj
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
        if value is None:
            if required:
                raise _Bad(f"missing:{name}")
            return None
    return _typed(value, kind, name)


def _typed(value: Any, kind: str, name: str) -> Any:
    if kind == "dict":
        if isinstance(value, dict):
            return value
    elif kind == "str":
        if isinstance(value, str):
            return value
    elif kind == "int":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    elif kind in ("float", "lat", "lon"):
        if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value):
            limit = {"lat": 90, "lon": 180}.get(kind)
            if limit is None or abs(value) <= limit:
                return float(value)
    elif kind == "epoch":
        if isinstance(value, str) and value.isascii() and value.isdigit():
            value = int(value)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            try:
                return datetime.fromtimestamp(value, UTC)
            except (OverflowError, OSError, ValueError):
                pass
    elif kind == "date" and isinstance(value, str):
        try:
            return parse_service_date(value).isoformat()
        except ValueError:
            pass
    raise _Bad(f"bad:{name}")


def _trip(obj: Any, base: str) -> Row:
    return {
        "trip_id": _at(obj, f"{base}.tripId", "str"),
        "route_id": _at(obj, f"{base}.routeId", "str"),
        "direction_id": _at(obj, f"{base}.directionId", "int"),
        "start_date": _at(obj, f"{base}.startDate", "date"),
        "start_time": _at(obj, f"{base}.startTime", "str"),
    }


def decode_vehicle(raw: bytes) -> Row | Quarantined:
    """One `vehicle_position` row."""
    try:
        o = _load(raw)
        _at(o, "vehicle", "dict", required=True)
        vehicle_id = _at(o, "vehicle.vehicle.id", "str") or _at(o, "id", "str", required=True)
        return {
            "vehicle_id": vehicle_id,
            **_trip(o, "vehicle.trip"),
            "trip_schedule_relationship": _at(o, "vehicle.trip.scheduleRelationship", "str"),
            "lat": _at(o, "vehicle.position.latitude", "lat", required=True),
            "lon": _at(o, "vehicle.position.longitude", "lon", required=True),
            "bearing": _at(o, "vehicle.position.bearing", "float"),
            "speed": _at(o, "vehicle.position.speed", "float"),
            "current_stop_sequence": _at(o, "vehicle.currentStopSequence", "int"),
            "stop_id": _at(o, "vehicle.stopId", "str"),
            "current_status": _at(o, "vehicle.currentStatus", "str"),
            "vehicle_ts": _at(o, "vehicle.timestamp", "epoch", required=True),
        }
    except _Bad as bad:
        return Quarantined(bad.reason, raw)


def decode_trip_update(raw: bytes) -> list[Row] | Quarantined:
    """One `trip_update` row per stop-time update; one row with no stop if there are none
    (a cancellation carries no stop-time updates)."""
    try:
        o = _load(raw)
        _at(o, "tripUpdate", "dict", required=True)
        _at(o, "tripUpdate.trip.tripId", "str", required=True)
        trip = {
            **_trip(o, "tripUpdate.trip"),
            "trip_schedule_relationship": _at(o, "tripUpdate.trip.scheduleRelationship", "str"),
            "vehicle_id": _at(o, "tripUpdate.vehicle.id", "str"),
            "entity_ts": _at(o, "tripUpdate.timestamp", "epoch"),
        }
        updates = o["tripUpdate"].get("stopTimeUpdate")
        if updates is None:
            updates = []
        if not isinstance(updates, list):
            raise _Bad("bad:tripUpdate.stopTimeUpdate")
        if not updates:
            return [{**trip, **dict.fromkeys(_STOP_FIELDS)}]
        return [{**trip, **_stop(u)} for u in updates]
    except _Bad as bad:
        return Quarantined(bad.reason, raw)


_STOP_FIELDS = ("stop_sequence", "stop_id", "arrival_ts", "departure_ts",
                "stop_schedule_relationship")  # fmt: skip
_STU = "tripUpdate.stopTimeUpdate[]"


def _stop(u: Any) -> Row:
    if not isinstance(u, dict):
        raise _Bad(f"bad:{_STU}")
    return {
        "stop_sequence": _at(u, "stopSequence", "int", label=f"{_STU}.stopSequence"),
        "stop_id": _at(u, "stopId", "str", label=f"{_STU}.stopId"),
        "arrival_ts": _at(u, "arrival.time", "epoch", label=f"{_STU}.arrival.time"),
        "departure_ts": _at(u, "departure.time", "epoch", label=f"{_STU}.departure.time"),
        "stop_schedule_relationship": _at(
            u, "scheduleRelationship", "str", label=f"{_STU}.scheduleRelationship"
        ),
    }


def _paths(value: Any, prefix: str = "") -> Iterator[str]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _paths(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(value, list):
        for v in value:
            yield from _paths(v, f"{prefix}[]")
    else:
        yield f"{prefix}:{type(value).__name__}"


def fingerprint(frames: Iterable[bytes]) -> str:
    """SHA-256 of the sorted set of field paths and JSON types across a snapshot's frames.
    Values and order don't matter; a new field, a dropped field, or a type change does."""
    seen: set[str] = set()
    for raw in frames:
        try:
            seen.update(_paths(json.loads(raw)))
        except (ValueError, RecursionError):
            seen.add("<unparseable>")
    return hashlib.sha256("\n".join(sorted(seen)).encode()).hexdigest()
