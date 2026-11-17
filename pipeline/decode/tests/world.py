"""A small synthetic world pushed through the real Python pipeline, for dbt tests.

Bronze (one schedule ZIP, vehicle and trip-update snapshots, their fetch-log lines) goes
through the real GTFS load, compaction, decode and sync, so dbt reads exactly the files and
schemas the pipeline writes. Nothing here touches the network.
"""

import gzip
import hashlib
import json
from datetime import date
from pathlib import Path

from ghostbus_decode.compact import compact_day
from ghostbus_decode.decode import decode_day
from ghostbus_decode.gtfs_tables import load_gtfs
from ghostbus_decode.sync import sync
from test_gtfs_tables import FILES, make_zip

DAY = date(2026, 11, 14)
GTFS_SHA = "cb1a2283abecc0af1619365ea0626262bc3d93d5e6bdd0df03288cd6120f6058"
GTFS_KEY = f"bronze/gtfs_static/dt=2026-11-13/{GTFS_SHA[:16]}.zip"


class Bucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def put(self, key: str, body: bytes) -> None:
        self.objects[key] = body

    def delete(self, key: str) -> None:
        del self.objects[key]


def _log(bucket: Bucket, day: str, hour: str, name: str, lines: list[str]) -> None:
    key = f"bronze/_fetch_log/dt={day}/hour={hour}/{name}.jsonl"
    bucket.objects[key] = bucket.objects.get(key, b"") + ("\n".join(lines) + "\n").encode()


def add_snapshots(bucket: Bucket, feed: str, cuts: list[tuple[str, list[str]]]) -> None:
    lines = []
    for at, frames in cuts:
        data = ("\n".join(frames) + "\n").encode()
        sha = hashlib.sha256(data).hexdigest()
        bucket.objects[f"bronze/{feed}/dt={at[:10]}/{sha[:16]}.ndjson.gz"] = gzip.compress(
            data, mtime=0
        )
        lines.append(json.dumps({"event": "fetch", "feed": feed, "fetched_at": at,
                                 "outcome": "written", "content_hash": sha,
                                 "partial": False, "n_entities": len(frames)}))  # fmt: skip
    _log(bucket, cuts[0][0][:10], cuts[0][0][11:13], feed, lines)


def build(tmp: Path, vehicles: list[tuple[str, list[str]]],
          trips: list[tuple[str, list[str]]]) -> Path:  # fmt: skip
    """Run the whole Python pipeline for DAY and return the synced data folder."""
    bucket = Bucket()
    bucket.objects[GTFS_KEY] = make_zip(FILES)
    written = {"event": "fetch", "feed": "gtfs_static", "fetched_at": "2026-11-13T11:00:00Z",
               "outcome": "written", "content_hash": GTFS_SHA, "object_key": GTFS_KEY}  # fmt: skip
    _log(bucket, "2026-11-13", "11", "gtfs", [json.dumps(written)])
    result = load_gtfs(bucket, tmp)
    assert not result.failed, result.failed
    for feed, cuts in (("vehicle_positions", vehicles), ("trip_updates", trips)):
        add_snapshots(bucket, feed, cuts)
        compact_day(bucket, feed, DAY, workdir=tmp)
        decode_day(bucket, feed, DAY, workdir=tmp)
    data = tmp / "data"
    sync(bucket, DAY, DAY, data)
    return data
