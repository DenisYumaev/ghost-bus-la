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
from datetime import datetime
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
            seen = ZipSighting(
                sha256=rec["content_hash"],
                first_seen_at=datetime.fromisoformat(rec["fetched_at"]),
                object_key=rec["object_key"],
            )
            kept = scan.written.get(seen.sha256)
            if kept is None or seen.first_seen_at < kept.first_seen_at:
                scan.written[seen.sha256] = seen
    return scan


def find_zips(keys: Iterable[str], scan: Scan) -> list[ZipSighting]:
    """One sighting per stored hash, ordered by first sighting.

    Raises MissingSighting for a stored ZIP with no `written` line: its first-seen time
    decides which schedule is in force, so it is never guessed. A `written` ZIP not in the
    listing yet (upload pending) is left for the next run.
    """
    by_prefix = {sha[:16]: seen for sha, seen in scan.written.items()}
    found: dict[str, ZipSighting] = {}
    for key in keys:
        match = _KEY.fullmatch(key)
        if match is None:
            raise ValueError(f"not a GTFS ZIP key: {key!r}")
        seen = by_prefix.get(match.group(2))
        if seen is None:
            raise MissingSighting(f"{key}: no written line in the fetch log for its day")
        found[seen.sha256] = seen
    return sorted(found.values(), key=lambda z: (z.first_seen_at, z.sha256))


def load_sightings(bucket: ReadBucket) -> list[ZipSighting]:
    """List the stored ZIPs, read the fetch log for the days they were stored, match them."""
    keys = [k for k in bucket.list_keys(GTFS_PREFIX) if k.endswith(".zip")]
    days = sorted({m.group(1) for k in keys if (m := _KEY.fullmatch(k))})
    lines: list[str] = []
    for day in days:
        for log_key in bucket.list_keys(f"{FETCH_LOG_PREFIX}dt={day}/"):
            lines.extend(bucket.get(log_key).decode().splitlines())
    return find_zips(keys, scan_lines(lines))
