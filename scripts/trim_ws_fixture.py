"""Trim a recording from record_ws.py into a small, committable test fixture.

Keeps every frame, in arrival order with its timing, for a deterministic subset of entities:
all canceled trips (up to a cap), any vehicle with no trip, any entity that joined late, then
the lowest-sorted remaining IDs until `max_entities`. Because each kept entity keeps all its
appearances, the fixture preserves the stream's real loop timing for those entities.

Frames are copied unchanged. Output is gzip with a fixed header, so the same input always
produces the same file. Must stay under the 1 MiB fixture limit (scripts/check_fixture_size.py).

Usage:
    uv run python scripts/trim_ws_fixture.py <recording.jsonl> <out.jsonl.gz> [max_entities]
"""

import gzip
import json
import sys
from pathlib import Path

LATE_JOIN_S = 15.0
MAX_CANCELED = 8


def select_entities(frames: list[tuple[float, str]], max_entities: int) -> set[str]:
    first_seen: dict[str, float] = {}
    canceled: set[str] = set()
    no_trip: set[str] = set()
    for t, raw in frames:
        msg = json.loads(raw)
        entity = str(msg["id"])
        first_seen.setdefault(entity, t)
        trip_update = msg.get("tripUpdate")
        if trip_update and trip_update.get("trip", {}).get("scheduleRelationship") == "CANCELED":
            canceled.add(entity)
        vehicle = msg.get("vehicle")
        if vehicle is not None and "trip" not in vehicle:
            no_trip.add(entity)

    chosen: list[str] = sorted(canceled)[:MAX_CANCELED]
    chosen += sorted(no_trip)[:3]
    chosen += sorted(e for e, t in first_seen.items() if t > LATE_JOIN_S)[:2]
    for entity in sorted(first_seen):
        if len(set(chosen)) >= max_entities:
            break
        chosen.append(entity)
    return set(chosen)


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    source, out = Path(argv[0]), Path(argv[1])
    max_entities = int(argv[2]) if len(argv) == 3 else 25

    frames = [(rec["t"], rec["raw"]) for rec in map(json.loads, source.open())]
    keep = select_entities(frames, max_entities)
    lines = [
        json.dumps({"t": t, "raw": raw}) + "\n"
        for t, raw in frames
        if str(json.loads(raw)["id"]) in keep
    ]
    out.write_bytes(gzip.compress("".join(lines).encode(), compresslevel=9, mtime=0))
    print(f"{len(keep)} entities, {len(lines)} frames, {out.stat().st_size} bytes -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
