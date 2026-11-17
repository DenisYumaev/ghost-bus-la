"""Tests for compaction: one UTC day of snapshots into one Parquet file per feed
(pipeline spec, section 3)."""

import gzip
import hashlib
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest
from ghostbus_decode.compact import (
    SUCCESS,
    compact_day,
    compacted_key,
    day_prefix,
)

DAY = date(2026, 11, 14)


def snapshot(*frames: str) -> tuple[str, bytes]:
    data = ("\n".join(frames) + "\n").encode()
    gz = gzip.compress(data, mtime=0)
    return hashlib.sha256(data).hexdigest(), gz


def key(feed: str, day: str, sha: str) -> str:
    return f"bronze/{feed}/dt={day}/{sha[:16]}.ndjson.gz"


def fetch(feed: str, at: str, outcome: str, sha: str | None, **extra: Any) -> str:
    return json.dumps(
        {"event": "fetch", "feed": feed, "fetched_at": at, "outcome": outcome,
         "content_hash": sha, "partial": False, "n_entities": 1,
         "object_key": key(feed, at[:10], sha) if sha else None, **extra}
    )  # fmt: skip


class FakeBucket:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.puts: list[str] = []
        self.deleted: list[str] = []

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def put(self, key: str, body: bytes) -> None:
        self.puts.append(key)
        self.objects[key] = body

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        del self.objects[key]


VP = "vehicle_positions"
SHA_A, GZ_A = snapshot('{"id": "1"}')
SHA_B, GZ_B = snapshot('{"id": "2"}')
SHA_Y, GZ_Y = snapshot('{"id": "yesterday"}')


def log(day: str, hour: str, *lines: str, name: str = "aaaa") -> dict[str, bytes]:
    return {
        f"bronze/_fetch_log/dt={day}/hour={hour}/{name}.jsonl": ("\n".join(lines) + "\n").encode()
    }


def read(bucket: FakeBucket, feed: str, tmp_path: Path) -> list[tuple[Any, ...]]:
    """All of the day's part files, as a reader globbing dt=<day>/*.parquet would see them."""
    out = tmp_path / "read"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    for k in bucket.list_keys(day_prefix(feed, DAY)):
        if k.endswith(".parquet"):
            (out / k.rsplit("/", 1)[-1]).write_bytes(bucket.objects[k])
    with duckdb.connect() as con:
        return con.execute(
            "SELECT CAST(timezone('UTC', fetched_at) AS VARCHAR), outcome, content_hash, "
            "object_key, partial, n_entities, payload FROM read_parquet(?) ORDER BY fetched_at",
            [str(out / "*.parquet")],
        ).fetchall()


def test_one_row_per_fetch_with_the_exact_stored_bytes(tmp_path: Path) -> None:
    bucket = FakeBucket({
        key(VP, "2026-11-14", SHA_A): GZ_A,
        key(VP, "2026-11-14", SHA_B): GZ_B,
        **log("2026-11-14", "05",
              fetch(VP, "2026-11-14T05:00:00Z", "written", SHA_A),
              fetch(VP, "2026-11-14T05:00:30Z", "written", SHA_B, partial=True)),
    })  # fmt: skip
    marker = compact_day(bucket, VP, DAY, workdir=tmp_path)
    rows = read(bucket, VP, tmp_path)
    assert [(r[0], r[1], r[2], r[4], bytes(r[6])) for r in rows] == [
        ("2026-11-14 05:00:00", "written", SHA_A, False, GZ_A),
        ("2026-11-14 05:00:30", "written", SHA_B, True, GZ_B),
    ]
    assert marker["rows"] == 2
    assert bucket.puts[-1] == day_prefix(VP, DAY) + SUCCESS


def test_the_same_bytes_at_two_times_are_two_rows(tmp_path: Path) -> None:
    # Content-addressed storage keeps the bytes once; each cut is still an observation.
    bucket = FakeBucket({
        key(VP, "2026-11-14", SHA_A): GZ_A,
        **log("2026-11-14", "05",
              fetch(VP, "2026-11-14T05:00:00Z", "written", SHA_A),
              fetch(VP, "2026-11-14T05:00:30Z", "duplicate", SHA_A)),
    })  # fmt: skip
    compact_day(bucket, VP, DAY, workdir=tmp_path)
    rows = read(bucket, VP, tmp_path)
    assert [(r[1], r[3]) for r in rows] == [
        ("written", key(VP, "2026-11-14", SHA_A)),
        ("duplicate", key(VP, "2026-11-14", SHA_A)),  # located by hash, not by its own key
    ]


def test_a_duplicate_after_midnight_finds_yesterdays_bytes(tmp_path: Path) -> None:
    bucket = FakeBucket({
        key(VP, "2026-11-13", SHA_Y): GZ_Y,
        **log("2026-11-14", "00", fetch(VP, "2026-11-14T00:00:00Z", "duplicate", SHA_Y)),
    })  # fmt: skip
    compact_day(bucket, VP, DAY, workdir=tmp_path)
    [row] = read(bucket, VP, tmp_path)
    assert (row[3], bytes(row[6])) == (key(VP, "2026-11-13", SHA_Y), GZ_Y)


def test_only_this_feed_this_day_and_content_outcomes(tmp_path: Path) -> None:
    bucket = FakeBucket({
        key(VP, "2026-11-14", SHA_A): GZ_A,
        **log("2026-11-14", "05",
              fetch(VP, "2026-11-14T05:00:00Z", "written", SHA_A),
              fetch(VP, "2026-11-14T05:00:30Z", "network_error", None, error="no_messages"),
              fetch("trip_updates", "2026-11-14T05:01:00Z", "written", SHA_B),
              json.dumps({"event": "disconnect", "feed": VP, "at": "2026-11-14T05:00:40Z"})),
    })  # fmt: skip
    compact_day(bucket, VP, DAY, workdir=tmp_path)
    assert [r[2] for r in read(bucket, VP, tmp_path)] == [SHA_A]


def test_lines_repeated_across_reuploaded_hour_files_count_once(tmp_path: Path) -> None:
    line = fetch(VP, "2026-11-14T05:00:00Z", "written", SHA_A)
    bucket = FakeBucket({
        key(VP, "2026-11-14", SHA_A): GZ_A,
        **log("2026-11-14", "05", line, name="first"),
        **log("2026-11-14", "05", line, fetch(VP, "2026-11-14T05:00:30Z", "written", SHA_B),
              name="second"),
        key(VP, "2026-11-14", SHA_B): GZ_B,
    })  # fmt: skip
    compact_day(bucket, VP, DAY, workdir=tmp_path)
    assert [r[2] for r in read(bucket, VP, tmp_path)] == [SHA_A, SHA_B]


def test_a_fetch_whose_object_never_arrived_is_counted_not_hidden(tmp_path: Path) -> None:
    bucket = FakeBucket({
        key(VP, "2026-11-14", SHA_A): GZ_A,
        **log("2026-11-14", "05",
              fetch(VP, "2026-11-14T05:00:00Z", "written", SHA_A),
              fetch(VP, "2026-11-14T05:00:30Z", "written", SHA_B)),
    })  # fmt: skip
    marker = compact_day(bucket, VP, DAY, workdir=tmp_path)
    assert marker["rows"] == 1
    assert marker["missing_objects"] == [SHA_B]


def test_rerunning_a_day_gives_identical_output(tmp_path: Path) -> None:
    bucket = FakeBucket({
        key(VP, "2026-11-14", SHA_A): GZ_A,
        **log("2026-11-14", "05", fetch(VP, "2026-11-14T05:00:00Z", "written", SHA_A)),
    })  # fmt: skip
    compact_day(bucket, VP, DAY, workdir=tmp_path)
    first = read(bucket, VP, tmp_path)
    compact_day(bucket, VP, DAY, workdir=tmp_path)
    assert read(bucket, VP, tmp_path) == first


def test_a_day_with_no_fetches_writes_an_empty_typed_file(tmp_path: Path) -> None:
    bucket = FakeBucket({})
    marker = compact_day(bucket, VP, DAY, workdir=tmp_path)
    assert marker["rows"] == 0
    assert read(bucket, VP, tmp_path) == []


def test_never_writes_under_bronze(tmp_path: Path) -> None:
    bucket = FakeBucket({
        key(VP, "2026-11-14", SHA_A): GZ_A,
        **log("2026-11-14", "05", fetch(VP, "2026-11-14T05:00:00Z", "written", SHA_A)),
    })  # fmt: skip
    compact_day(bucket, VP, DAY, workdir=tmp_path)
    assert bucket.puts
    assert all(k.startswith("derived/compacted/") for k in bucket.puts)


def test_rejects_an_unknown_feed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="feed"):
        compact_day(FakeBucket({}), "gtfs_static", DAY, workdir=tmp_path)


def test_temp_files_are_removed(tmp_path: Path) -> None:
    bucket = FakeBucket({
        key(VP, "2026-11-14", SHA_A): GZ_A,
        **log("2026-11-14", "05", fetch(VP, "2026-11-14T05:00:00Z", "written", SHA_A)),
    })  # fmt: skip
    compact_day(bucket, VP, DAY, workdir=tmp_path)
    assert not any(p.suffix in (".duckdb", ".parquet") for p in tmp_path.rglob("*"))


def test_an_open_day_is_refused() -> None:
    from ghostbus_decode.compact import check_closed

    with pytest.raises(ValueError, match="not closed"):
        check_closed(date(2026, 11, 17), today=date(2026, 11, 17))
    check_closed(date(2026, 11, 16), today=date(2026, 11, 17))


def test_an_unparseable_fetch_log_line_is_skipped(tmp_path: Path) -> None:
    bucket = FakeBucket({
        key(VP, "2026-11-14", SHA_A): GZ_A,
        **log("2026-11-14", "05", "{truncated",
              fetch(VP, "2026-11-14T05:00:00Z", "written", SHA_A)),
    })  # fmt: skip
    assert compact_day(bucket, VP, DAY, workdir=tmp_path)["rows"] == 1


def many_fetches(n: int) -> FakeBucket:
    objects: dict[str, bytes] = {}
    lines = []
    for i in range(n):
        sha, gz = snapshot(f'{{"id": "{i}"}}')
        objects[key(VP, "2026-11-14", sha)] = gz
        lines.append(fetch(VP, f"2026-11-14T05:{i // 2:02d}:{30 * (i % 2):02d}Z", "written", sha))
    return FakeBucket({**objects, **log("2026-11-14", "05", *lines)})


def test_a_big_day_is_split_into_bounded_parts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ghostbus_decode.compact._PART_ROWS", 3)
    bucket = many_fetches(7)
    marker = compact_day(bucket, VP, DAY, workdir=tmp_path)
    assert marker["parts"] == 3
    assert compacted_key(VP, DAY, 2) in bucket.objects
    rows = read(bucket, VP, tmp_path)
    assert len(rows) == 7
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)


def test_a_rerun_with_fewer_parts_deletes_the_stale_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ghostbus_decode.compact._PART_ROWS", 3)
    bucket = many_fetches(7)
    compact_day(bucket, VP, DAY, workdir=tmp_path)
    monkeypatch.setattr("ghostbus_decode.compact._PART_ROWS", 200)
    compact_day(bucket, VP, DAY, workdir=tmp_path)
    assert sorted(bucket.deleted) == [compacted_key(VP, DAY, 1), compacted_key(VP, DAY, 2)]
    assert len(read(bucket, VP, tmp_path)) == 7
