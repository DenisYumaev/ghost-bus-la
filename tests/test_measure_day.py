"""Tests for scripts/measure_day.py: the aggregation behind the measured-day report."""

import json

from measure_day import report, summarize


def fetch(
    feed: str, at: str, outcome: str, raw: int = 0, gz: int = 0, partial: bool = False
) -> str:
    return json.dumps(
        {"event": "fetch", "feed": feed, "fetched_at": at, "outcome": outcome,
         "bytes": raw or None, "bytes_gz": gz or None, "partial": partial}
    )  # fmt: skip


def test_counts_outcomes_and_bytes_only_for_the_requested_utc_date() -> None:
    lines = {
        fetch("vehicle_positions", "2026-11-14T00:00:30Z", "written", 100, 10),
        fetch("vehicle_positions", "2026-11-14T00:01:00Z", "written", 200, 20, partial=True),
        fetch("vehicle_positions", "2026-11-15T00:00:00Z", "written", 999, 99),  # next day
        fetch("trip_updates", "2026-11-14T00:01:00Z", "network_error"),
        fetch("gtfs_static", "2026-11-14T03:00:00Z", "written", 5, 5),  # not a stream
        json.dumps({"event": "disconnect", "feed": "trip_updates", "at": "2026-11-14T01:00:00Z"}),
        json.dumps({"event": "upload", "at": "2026-11-14T01:00:00Z", "outcome": "written"}),
    }
    days = summarize(lines, "2026-11-14")

    vp, tu = days["vehicle_positions"], days["trip_updates"]
    assert (vp.expected, vp.attempted, vp.partial) == (2880, 2, 1)
    assert (vp.raw_bytes, vp.gz_bytes) == (300, 30)
    assert tu.expected == 1440
    assert tu.outcomes == {"network_error": 1}
    assert (tu.raw_bytes, tu.disconnects) == (0, 1)


def test_partial_counts_only_stored_cuts_and_empty_cuts_report_their_reason() -> None:
    empty = json.dumps(
        {"event": "fetch", "feed": "trip_updates", "fetched_at": "2026-11-14T02:00:00Z",
         "outcome": "network_error", "bytes": None, "bytes_gz": None, "partial": True,
         "error": "no_messages"}
    )  # fmt: skip
    lines = {empty, fetch("trip_updates", "2026-11-14T02:01:00Z", "written", 10, 1, True)}
    day = summarize(lines, "2026-11-14")["trip_updates"]
    assert day.partial == 1  # the empty cut stored nothing, so it isn't a partial snapshot
    assert day.empty_reasons == {"no_messages": 1}


def test_duplicate_lines_from_a_reuploaded_hour_count_once() -> None:
    line = fetch("trip_updates", "2026-11-14T05:00:00Z", "written", 10, 1)
    days = summarize({line, line}, "2026-11-14")  # a set: the union of both uploads
    assert days["trip_updates"].attempted == 1


def test_report_shows_attempt_percentage_and_total() -> None:
    lines = {fetch("trip_updates", "2026-11-14T00:01:00Z", "written", 10**9, 10**8)}
    text = report(summarize(lines, "2026-11-14"))
    assert "1 (0.07%)" in text
    assert "Total gzipped: 0.100 GB" in text
