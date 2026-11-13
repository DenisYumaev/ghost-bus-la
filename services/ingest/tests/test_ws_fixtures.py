"""Contract for the recorded WebSocket fixtures (hard rule 10: tests run on recorded real data).

The snapshot tests depend on these cases being present. If a re-recorded or re-trimmed fixture
loses one, this file fails first, with a clear message, instead of a confusing failure elsewhere.
"""

import gzip
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> list[tuple[float, str]]:
    with gzip.open(FIXTURES / name, "rt") as f:
        return [(rec["t"], rec["raw"]) for rec in map(json.loads, f)]


@pytest.mark.parametrize("name", ["vehicle_positions_45s.jsonl.gz", "trip_updates_45s.jsonl.gz"])
def test_frames_are_in_arrival_order_and_span_the_recording(name: str) -> None:
    times = [t for t, _ in load(name)]
    assert times == sorted(times)
    assert times[-1] - times[0] >= 40, "need at least 40 s to cover several server loops"


@pytest.mark.parametrize("name", ["vehicle_positions_45s.jsonl.gz", "trip_updates_45s.jsonl.gz"])
def test_every_frame_is_a_json_object_with_an_id(name: str) -> None:
    for _, raw in load(name):
        message = json.loads(raw)
        assert isinstance(message, dict)
        assert "id" in message


@pytest.mark.parametrize("name", ["vehicle_positions_45s.jsonl.gz", "trip_updates_45s.jsonl.gz"])
def test_entities_reappear_several_times(name: str) -> None:
    counts: dict[str, int] = {}
    for _, raw in load(name):
        entity = str(json.loads(raw)["id"])
        counts[entity] = counts.get(entity, 0) + 1
    assert len(counts) >= 20
    assert sum(1 for n in counts.values() if n >= 2) >= 20, "latest-message-wins needs repeats"


def test_trip_updates_include_canceled_trips() -> None:
    canceled = {
        json.loads(raw)["id"]
        for _, raw in load("trip_updates_45s.jsonl.gz")
        if json.loads(raw)["tripUpdate"]["trip"].get("scheduleRelationship") == "CANCELED"
    }
    assert len(canceled) >= 3


def test_vehicle_positions_include_a_vehicle_with_no_trip() -> None:
    assert any(
        "trip" not in json.loads(raw)["vehicle"]
        for _, raw in load("vehicle_positions_45s.jsonl.gz")
    )


@pytest.mark.parametrize("name", ["vehicle_positions_45s.jsonl.gz", "trip_updates_45s.jsonl.gz"])
def test_some_entity_joins_after_the_initial_burst(name: str) -> None:
    first_seen: dict[str, float] = {}
    for t, raw in load(name):
        first_seen.setdefault(str(json.loads(raw)["id"]), t)
    assert any(t > 15 for t in first_seen.values()), "need an entity that appears mid-recording"
