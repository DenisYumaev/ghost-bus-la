"""Tests for decoding one WebSocket frame into typed rows (pipeline spec, section 3).

Frames below are copied from the recorded fixtures (services/ingest/tests/fixtures/), which
are real Metro messages from 2026-11-12.
"""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from ghostbus_decode.frames import Quarantined, decode_trip_update, decode_vehicle, fingerprint
from hypothesis import given
from hypothesis import strategies as st

VEHICLE_NO_TRIP = (
    '{"id": "10019", "vehicle": {"position": {"latitude": 33.85826, "longitude": -118.32873, '
    '"speed": 0.0}, "timestamp": "1794539562", "vehicle": {"id": "10019", "label": "10019"}}, '
    '"route_code": ""}'
)
VEHICLE_ON_TRIP = json.dumps({
    "id": "3912", "route_code": "720",
    "vehicle": {
        "trip": {"tripId": "72001001660852-JUNE26", "startTime": "16:08:00",
                 "startDate": "20261112", "scheduleRelationship": "SCHEDULED",
                 "routeId": "720-13201", "directionId": 1},
        "position": {"latitude": 34.0617, "longitude": -118.3087, "bearing": 270.0, "speed": 4.5},
        "currentStopSequence": 14, "currentStatus": "IN_TRANSIT_TO", "stopId": "15612",
        "timestamp": "1794539550", "vehicle": {"id": "3912", "label": "3912"},
    },
})  # fmt: skip
CANCELED = (
    '{"id": "10002011531649-JUNE26", "tripUpdate": {"trip": {"tripId": "10002011531649-JUNE26", '
    '"startTime": "16:49:00", "startDate": "20261112", "scheduleRelationship": "CANCELED", '
    '"routeId": "2-13201", "directionId": 0}, "timestamp": "1794539561"}, "route_code": ""}'
)
SCHEDULED = json.dumps({
    "id": "T1", "route_code": "",
    "tripUpdate": {
        "trip": {"tripId": "T1", "startTime": "25:10:00", "startDate": "20261112",
                 "scheduleRelationship": "SCHEDULED", "routeId": "2-13201", "directionId": 1},
        "stopTimeUpdate": [
            {"stopSequence": 3, "stopId": "2081", "arrival": {"time": "1794539700"},
             "departure": {"time": "1794539730"}, "scheduleRelationship": "SCHEDULED"},
            {"stopSequence": 4, "stopId": "2082", "scheduleRelationship": "NO_DATA"},
        ],
        "vehicle": {"id": "3912"}, "timestamp": "1794539561",
    },
})  # fmt: skip


TRIP = "tripUpdate.trip"


def ts(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


def test_vehicle_without_a_trip() -> None:
    row = decode_vehicle(VEHICLE_NO_TRIP.encode())
    assert not isinstance(row, Quarantined)
    assert row["vehicle_id"] == "10019"
    assert (row["lat"], row["lon"], row["speed"], row["bearing"]) == (
        33.85826,
        -118.32873,
        0.0,
        None,
    )
    assert row["vehicle_ts"] == ts(1794539562)
    assert row["trip_id"] is None
    assert row["start_date"] is None


def test_vehicle_on_a_trip() -> None:
    row = decode_vehicle(VEHICLE_ON_TRIP.encode())
    assert not isinstance(row, Quarantined)
    assert (row["trip_id"], row["route_id"], row["direction_id"]) == (
        "72001001660852-JUNE26", "720-13201", 1,
    )  # fmt: skip
    assert (row["start_date"], row["start_time"]) == ("2026-11-12", "16:08:00")
    assert (row["current_stop_sequence"], row["stop_id"], row["current_status"]) == (
        14, "15612", "IN_TRANSIT_TO",
    )  # fmt: skip


def test_a_canceled_trip_is_one_row_with_no_stop() -> None:
    rows = decode_trip_update(CANCELED.encode())
    assert not isinstance(rows, Quarantined)
    [row] = rows
    assert row["trip_schedule_relationship"] == "CANCELED"
    assert (row["stop_sequence"], row["stop_id"], row["arrival_ts"]) == (None, None, None)
    assert (row["start_date"], row["start_time"]) == ("2026-11-12", "16:49:00")
    assert row["entity_ts"] == ts(1794539561)


def test_one_row_per_stop_time_update() -> None:
    rows = decode_trip_update(SCHEDULED.encode())
    assert not isinstance(rows, Quarantined)
    assert [(r["stop_sequence"], r["stop_id"], r["arrival_ts"], r["departure_ts"],
             r["stop_schedule_relationship"]) for r in rows] == [
        (3, "2081", ts(1794539700), ts(1794539730), "SCHEDULED"),
        (4, "2082", None, None, "NO_DATA"),
    ]  # fmt: skip
    assert {r["vehicle_id"] for r in rows} == {"3912"}
    assert {r["start_time"] for r in rows} == {"25:10:00"}  # text: can pass 24:00


def obj(raw: str) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(raw)
    return value


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda o: "not json {", "not_json"),
        (lambda o: "[1, 2]", "not_object"),
        (lambda o: json.dumps({**obj(VEHICLE_NO_TRIP), "vehicle": None}), "missing:vehicle"),
        (lambda o: VEHICLE_NO_TRIP.replace('"latitude": 33.85826', '"latitude": "33.8"'),
         "bad:vehicle.position.latitude"),
        (lambda o: VEHICLE_NO_TRIP.replace('"latitude": 33.85826', '"latitude": 91.0'),
         "bad:vehicle.position.latitude"),
        (lambda o: VEHICLE_NO_TRIP.replace('"latitude": 33.85826', '"latitude": NaN'),
         "bad:vehicle.position.latitude"),
        (lambda o: VEHICLE_NO_TRIP.replace('"timestamp": "1794539562"', '"timestamp": "17x"'),
         "bad:vehicle.timestamp"),
        (lambda o: VEHICLE_NO_TRIP.replace('"timestamp": "1794539562"', '"timestamp": true'),
         "bad:vehicle.timestamp"),
    ],
)  # fmt: skip
def test_bad_vehicle_frames_are_quarantined_with_a_reason(change: Any, reason: str) -> None:
    raw = change(None).encode()
    result = decode_vehicle(raw)
    assert isinstance(result, Quarantined)
    assert result.reason == reason
    assert result.raw == raw


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (CANCELED.replace('"directionId": 0', '"directionId": 0.5'), f"bad:{TRIP}.directionId"),
        (CANCELED.replace('"directionId": 0', '"directionId": true'), f"bad:{TRIP}.directionId"),
        (CANCELED.replace('"startDate": "20261112"', '"startDate": "2026-11-12"'),
         "bad:tripUpdate.trip.startDate"),
        (CANCELED.replace('"tripId": "10002011531649-JUNE26", ', ""), f"missing:{TRIP}.tripId"),
        (SCHEDULED.replace('"stopSequence": 3', '"stopSequence": "3"'),
         "bad:tripUpdate.stopTimeUpdate[].stopSequence"),
        (SCHEDULED.replace('"time": "1794539700"', '"time": "-5"'),
         "bad:tripUpdate.stopTimeUpdate[].arrival.time"),
    ],
)  # fmt: skip
def test_bad_trip_updates_are_quarantined_with_a_reason(raw: str, reason: str) -> None:
    result = decode_trip_update(raw.encode())
    assert isinstance(result, Quarantined)
    assert result.reason == reason


def test_unknown_extra_fields_are_tolerated_and_show_in_the_fingerprint() -> None:
    extra = json.dumps({**obj(VEHICLE_NO_TRIP), "occupancyStatus": "FULL"})
    assert not isinstance(decode_vehicle(extra.encode()), Quarantined)
    assert fingerprint([extra.encode()]) != fingerprint([VEHICLE_NO_TRIP.encode()])


def test_fingerprint_ignores_values_and_order() -> None:
    other = VEHICLE_NO_TRIP.replace("33.85826", "34.0").replace("10019", "777")
    assert fingerprint([VEHICLE_NO_TRIP.encode(), other.encode()]) == fingerprint([other.encode()])


json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=8),
    lambda inner: (
        st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=8), inner, max_size=4)
    ),
    max_leaves=12,
)


@given(json_values)
def test_any_json_decodes_or_is_quarantined_never_raises(value: Any) -> None:
    raw = json.dumps(value).encode()
    for decode in (decode_vehicle, decode_trip_update):
        decode(raw)  # returns rows or Quarantined; must not raise


@given(st.binary(max_size=64))
def test_any_bytes_decode_or_are_quarantined(raw: bytes) -> None:
    decode_vehicle(raw)
    decode_trip_update(raw)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (json.dumps({"id": "1", "vehicle": "x"}), "bad:vehicle"),
        (VEHICLE_NO_TRIP.replace('"timestamp": "1794539562"', '"timestamp": 99999999999999999'),
         "bad:vehicle.timestamp"),
        (VEHICLE_NO_TRIP.replace('"id": "10019", "label"', '"id": 10019, "label"'),
         "bad:vehicle.vehicle.id"),
    ],
)  # fmt: skip
def test_more_bad_vehicles(raw: str, reason: str) -> None:
    result = decode_vehicle(raw.encode())
    assert isinstance(result, Quarantined)
    assert result.reason == reason


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"stopTimeUpdate": "x"}, "bad:tripUpdate.stopTimeUpdate"),
        ({"stopTimeUpdate": ["x"]}, "bad:tripUpdate.stopTimeUpdate[]"),
    ],
)
def test_malformed_stop_time_updates(change: dict[str, Any], reason: str) -> None:
    frame = obj(CANCELED)
    frame["tripUpdate"].update(change)
    result = decode_trip_update(json.dumps(frame).encode())
    assert isinstance(result, Quarantined)
    assert result.reason == reason


def test_an_empty_stop_time_update_list_is_one_row() -> None:
    frame = obj(CANCELED)
    frame["tripUpdate"]["stopTimeUpdate"] = []
    rows = decode_trip_update(json.dumps(frame).encode())
    assert not isinstance(rows, Quarantined)
    assert len(rows) == 1


@pytest.mark.parametrize("direction", [2, -1])
def test_direction_must_be_zero_or_one(direction: int) -> None:
    raw = CANCELED.replace('"directionId": 0', f'"directionId": {direction}')
    result = decode_trip_update(raw.encode())
    assert isinstance(result, Quarantined)
    assert result.reason == "bad:tripUpdate.trip.directionId"


def test_unwrap_passes_ordinary_lines_through() -> None:
    from ghostbus_decode.frames import unwrap

    assert unwrap(VEHICLE_NO_TRIP.encode()) == VEHICLE_NO_TRIP.encode()
    assert isinstance(unwrap(b'{"_unframed_b64": "x", "extra": 1}'), Quarantined)
