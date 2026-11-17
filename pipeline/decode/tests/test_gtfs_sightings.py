"""Tests for finding GTFS ZIPs in bronze and when each was first seen (pipeline spec, section 4).

The fetch-log lines below copy the shape of real lines from 2026-11-15 to 2026-11-17.
"""

import json
from datetime import UTC, datetime

import pytest
from ghostbus_decode.gtfs_sightings import (
    GTFS_PREFIX,
    MissingSighting,
    find_zips,
    load_sightings,
    scan_lines,
)
from hypothesis import given
from hypothesis import strategies as st

SHA = "cb1a2283abecc0af1619365ea0626262bc3d93d5e6bdd0df03288cd6120f6058"
SHA_B = "b" * 64
KEY = f"{GTFS_PREFIX}dt=2026-11-15/{SHA[:16]}.zip"
KEY_B = f"{GTFS_PREFIX}dt=2026-11-20/{SHA_B[:16]}.zip"


def gtfs_line(at: str, outcome: str, sha: str = SHA, key: str | None = None) -> str:
    # A duplicate's object_key uses the day of the duplicate, where nothing is stored.
    day = at[:10]
    return json.dumps(
        {"event": "fetch", "fetched_at": at, "feed": "gtfs_static", "url_key": "gtfs_bus_gitlab",
         "http_status": 200, "content_hash": sha, "outcome": outcome,
         "object_key": key or f"{GTFS_PREFIX}dt={day}/{sha[:16]}.zip"}
    )  # fmt: skip


WRITTEN = gtfs_line("2026-11-15T15:13:04.305Z", "written")
DUP_1 = gtfs_line("2026-11-16T11:00:00.060Z", "duplicate")
DUP_2 = gtfs_line("2026-11-17T02:31:41.011Z", "duplicate")


def test_real_history_gives_one_zip_dated_from_its_written_line() -> None:
    [z] = find_zips([KEY], scan_lines([DUP_2, WRITTEN, DUP_1]))
    assert z.sha256 == SHA
    assert z.object_key == KEY
    assert z.first_seen_at == datetime(2026, 11, 15, 15, 13, 4, 305000, tzinfo=UTC)


def test_a_duplicates_object_key_is_never_used() -> None:
    # Only duplicates: their keys (dt=2026-11-16) point at nothing, so they can't locate it.
    scan = scan_lines([DUP_1, DUP_2])
    assert scan.written == {}
    assert scan.duplicates == 2


def test_lines_that_are_not_stored_gtfs_zips_are_ignored() -> None:
    maintenance_page = json.dumps(
        {"event": "fetch", "feed": "gtfs_static", "fetched_at": "2026-11-18T11:00:00Z",
         "outcome": "http_error", "content_hash": "e" * 64, "object_key": None,
         "error": "body is not a ZIP"}
    )  # fmt: skip
    stream = json.dumps(
        {"event": "fetch", "feed": "vehicle_positions", "fetched_at": "2026-11-15T15:13:00Z",
         "outcome": "written", "content_hash": "f" * 64, "object_key": "bronze/vehicle_positions/x"}
    )  # fmt: skip
    upload = json.dumps({"event": "upload", "at": "2026-11-15T15:13:05Z", "outcome": "written"})
    scan = scan_lines([maintenance_page, stream, upload, WRITTEN])
    assert list(scan.written) == [SHA]


def test_a_zip_stored_under_two_days_counts_from_the_earlier() -> None:
    later_key = f"{GTFS_PREFIX}dt=2026-11-19/{SHA[:16]}.zip"
    rewritten = gtfs_line("2026-11-19T11:00:00Z", "written", key=later_key)
    [z] = find_zips([later_key, KEY], scan_lines([rewritten, WRITTEN]))
    assert (z.object_key, z.first_seen_at.day) == (KEY, 15)


def test_an_object_without_a_written_line_stops_the_load() -> None:
    # Don't guess a first-seen time: it decides which schedule is in force.
    with pytest.raises(MissingSighting, match=SHA_B[:16]):
        find_zips([KEY, KEY_B], scan_lines([WRITTEN]))


def test_a_written_zip_not_uploaded_yet_is_left_for_the_next_run() -> None:
    written_b = gtfs_line("2026-11-20T11:00:00Z", "written", sha=SHA_B)
    scan = scan_lines([WRITTEN, written_b])
    assert [z.sha256 for z in find_zips([KEY], scan)] == [SHA]


def test_unparseable_lines_are_counted_not_fatal() -> None:
    scan = scan_lines(["{not json", "", WRITTEN])
    assert (scan.skipped, list(scan.written)) == (1, [SHA])


def test_rejects_a_key_that_is_not_a_gtfs_zip() -> None:
    with pytest.raises(ValueError, match="not a GTFS ZIP key"):
        find_zips(["bronze/gtfs_static/dt=2026-11-15/notahash.zip"], scan_lines([]))


@given(st.permutations([WRITTEN, DUP_1, DUP_2, gtfs_line("2026-11-15T15:20:00Z", "written")]))
def test_line_order_does_not_matter_and_the_earliest_written_wins(lines: list[str]) -> None:
    [z] = find_zips([KEY], scan_lines(lines))
    assert z.first_seen_at == datetime(2026, 11, 15, 15, 13, 4, 305000, tzinfo=UTC)


# --- reading from S3 --------------------------------------------------------------------------


class FakeBucket:
    """In-memory stand-in for the S3 reader: records which keys were read."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.read: list[str] = []

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))

    def get(self, key: str) -> bytes:
        self.read.append(key)
        return self.objects[key]


def test_load_reads_only_the_fetch_log_days_that_hold_a_zip() -> None:
    log = "bronze/_fetch_log/dt={}/hour={}/{}.jsonl"
    bucket = FakeBucket(
        {
            KEY: b"zip bytes",
            log.format("2026-11-15", "15", "aaaa"): (WRITTEN + "\n").encode(),
            log.format("2026-11-15", "16", "bbbb"): b'{"event": "fetch", "feed": "x"}\n',
            log.format("2026-11-16", "11", "cccc"): (DUP_1 + "\n").encode(),
        }
    )
    [z] = load_sightings(bucket)
    assert z.object_key == KEY
    assert all("dt=2026-11-15" in k for k in bucket.read)  # not Nov 16, and not the ZIP itself
    assert len(bucket.read) == 2


def test_load_with_no_zips_reads_nothing() -> None:
    bucket = FakeBucket({"bronze/_fetch_log/dt=2026-11-15/hour=15/a.jsonl": WRITTEN.encode()})
    assert load_sightings(bucket) == []
    assert bucket.read == []


def test_s3_bucket_follows_pagination_and_reads_bodies() -> None:
    import io

    import boto3
    from botocore.response import StreamingBody
    from botocore.stub import Stubber
    from ghostbus_decode.gtfs_sightings import S3Bucket

    client = boto3.client(
        "s3", region_name="us-west-2", aws_access_key_id="testing",
        aws_secret_access_key="testing",  # noqa: S106 - deliberately fake; Stubber blocks network
    )  # fmt: skip
    with Stubber(client) as stub:
        stub.add_response(
            "list_objects_v2",
            {"Contents": [{"Key": "p/a"}], "IsTruncated": True, "NextContinuationToken": "t"},
            {"Bucket": "b", "Prefix": "p/"},
        )
        stub.add_response(
            "list_objects_v2",
            {"Contents": [{"Key": "p/b"}], "IsTruncated": False},
            {"Bucket": "b", "Prefix": "p/", "ContinuationToken": "t"},
        )
        stub.add_response(
            "get_object",
            {"Body": StreamingBody(io.BytesIO(b"hello"), 5)},
            {"Bucket": "b", "Key": "p/a"},
        )
        bucket = S3Bucket(client, "b")
        assert bucket.list_keys("p/") == ["p/a", "p/b"]
        assert bucket.get("p/a") == b"hello"
        stub.assert_no_pending_responses()
