"""Find the GTFS ZIPs in bronze and when each was first seen (pipeline spec, section 4).

Two sources, each trusted for one thing:

- **The bronze listing** says which ZIPs exist: `bronze/gtfs_static/dt=<UTC day>/<sha16>.zip`.
- **The fetch log** says when each was first seen: the earliest `written` line for its hash.

A `duplicate` line is never used to locate a ZIP. Ingest builds its `object_key` from the day
of the duplicate (`dt=<that day>`), but the bytes were stored on the day they were first
written, so that key points at nothing. Duplicates don't move the first sighting either:
a hash is always written before it can be a duplicate.

A ZIP is stored under the UTC day of its `written` fetch, so only that day's fetch log is
read: about 24 small objects per version, not the whole history.

Read-only: nothing here writes to S3 (hard rule 1).
"""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ghostbus_decode.s3 import ReadBucket

GTFS_PREFIX = "bronze/gtfs_static/"
FETCH_LOG_PREFIX = "bronze/_fetch_log/"
FEED = "gtfs_static"
_KEY = re.compile(r"bronze/gtfs_static/dt=([0-9]{4}-[0-9]{2}-[0-9]{2})/([0-9a-f]{16})\.zip")


class MissingSighting(Exception):
    """A ZIP is in bronze but no fetch-log line says when it was written."""


@dataclass(frozen=True)
class ZipSighting:
    """A stored ZIP: where it is, and when ingest first wrote it."""

    sha256: str
    first_seen_at: datetime  # aware UTC
    object_key: str


@dataclass
class Scan:
    """What a pass over fetch-log lines found."""

    written: dict[str, ZipSighting] = field(default_factory=dict)  # earliest per hash
    duplicates: int = 0
    skipped: int = 0  # lines that weren't JSON objects


def scan_lines(lines: Iterable[str]) -> Scan:
    scan = Scan()
    for line in lines:
        if not line.strip():
            continue
        try:
            rec: Any = json.loads(line)
        except json.JSONDecodeError:
            scan.skipped += 1
            continue
        if not isinstance(rec, dict) or rec.get("event") != "fetch" or rec.get("feed") != FEED:
            continue
        if rec.get("outcome") == "duplicate":
            scan.duplicates += 1
        elif rec.get("outcome") == "written":
            try:
                seen = ZipSighting(
                    sha256=str(rec["content_hash"]),
                    first_seen_at=datetime.fromisoformat(rec["fetched_at"]),
                    object_key=str(rec["object_key"]),
                )
            except (KeyError, TypeError, ValueError):
                scan.skipped += 1  # a corrupted line; ingest always writes these fields
                continue
            kept = scan.written.get(seen.sha256)
            if kept is None or seen.first_seen_at < kept.first_seen_at:
                scan.written[seen.sha256] = seen
    return scan


@dataclass(frozen=True)
class Found:
    zips: list[ZipSighting]  # ordered by first sighting
    waiting: list[str]  # stored keys whose fetch-log hour isn't uploaded yet


def find_zips(keys: Iterable[str], scan: Scan, today: date) -> Found:
    """One sighting per stored hash, located by the bronze listing, timed by the fetch log.

    The location always comes from the listing, never from a log line: a `written` line can
    name a key whose upload never happened (spool lost before upload, then written again
    later), and if several keys hold one hash, the earliest listed one is used.

    A stored ZIP with no `written` line is normal for about an hour: ingest uploads the ZIP
    within seconds but the fetch-log hour only when the hour closes. ZIPs stored today or
    yesterday (UTC) are reported as `waiting` and picked up on a later run. Anything older
    raises MissingSighting: its first-seen time decides which schedule is in force, so it is
    never guessed (pipeline spec, section 4).
    """
    by_prefix = {sha[:16]: seen for sha, seen in scan.written.items()}
    listed: dict[str, list[str]] = {}
    waiting = []
    for key in sorted(keys):
        match = _KEY.fullmatch(key)
        if match is None:
            raise ValueError(f"not a GTFS ZIP key: {key!r}")
        stored_on, sha16 = date.fromisoformat(match.group(1)), match.group(2)
        seen = by_prefix.get(sha16)
        if seen is None:
            if stored_on >= today - timedelta(days=1):
                waiting.append(key)
                continue
            raise MissingSighting(f"{key}: no written line in the fetch log for its day")
        listed.setdefault(seen.sha256, []).append(key)
    zips = [
        ZipSighting(sha, scan.written[sha].first_seen_at, min(ks)) for sha, ks in listed.items()
    ]
    zips.sort(key=lambda z: (z.first_seen_at, z.sha256))
    return Found(zips, waiting)


def load_sightings(bucket: ReadBucket, today: date | None = None) -> Found:
    """List the stored ZIPs, read the fetch log for the days they were stored, match them.

    Relies on ingest's contract that a ZIP's key and its `written` line share one timestamp
    (`GtfsDownloader._store` passes the same `now` to the spool and the fetch log), so the
    line is in the fetch log of the key's `dt=` day.
    """
    keys = [k for k in bucket.list_keys(GTFS_PREFIX) if k.endswith(".zip")]
    days = sorted({m.group(1) for k in keys if (m := _KEY.fullmatch(k))})
    lines: list[str] = []
    for day in days:
        for log_key in bucket.list_keys(f"{FETCH_LOG_PREFIX}dt={day}/"):
            lines.extend(bucket.get(log_key).decode().splitlines())
    return find_zips(keys, scan_lines(lines), today or datetime.now(UTC).date())
