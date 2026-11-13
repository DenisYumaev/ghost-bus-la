"""The local spool: every snapshot lands on disk before it goes to S3 (pipeline spec, section 2.4).

If S3 is unreachable, ingest keeps spooling and the uploader catches up later, so an S3 outage
costs no data. Writes are atomic: a crash never leaves a half-written file where the uploader or
the detector could read it.

Layout:
    <root>/<feed>/<YYYYMMDDTHHMMSSZ>_<sha16>.ndjson.gz   a snapshot, named by cut time
    <root>/<feed>/<same name>.uploaded                    marker: stored in S3 (written or 412)
    <root>/<feed>/<same name>.tmp                         in progress; never read
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ghostbus_ingest.snapshot import Snapshot

FEEDS = frozenset({"vehicle_positions", "trip_updates"})
EXTENSION = ".ndjson.gz"
UPLOADED_SUFFIX = ".uploaded"
TMP_SUFFIX = ".tmp"


def _utc(at: float) -> datetime:
    return datetime.fromtimestamp(at, tz=UTC)


def spool_name(snap: Snapshot) -> str:
    """`<cut time>_<sha16>.ndjson.gz`. The time prefix lets readers process files in order."""
    return f"{_utc(snap.cut_at):%Y%m%dT%H%M%SZ}_{snap.sha16}{EXTENSION}"


def object_key(snap: Snapshot) -> str:
    """The content-addressed S3 key (ADR-004). `dt` is the UTC fetch date, a storage partition."""
    return f"bronze/{snap.feed}/dt={_utc(snap.cut_at):%Y-%m-%d}/{snap.sha16}{EXTENSION}"


@dataclass(frozen=True)
class SpoolResult:
    outcome: Literal["written", "duplicate"]
    path: Path | None  # None for a duplicate: nothing was stored
    object_key: str


def _fsync_dir(directory: Path) -> None:
    """Make a rename durable: the new directory entry must reach the disk too."""
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Spool:
    def __init__(self, root: Path) -> None:
        self.root = root
        # Local duplicate shortcut (spec 2.4, step 2): the previous stored hash, per feed.
        # Memory only; after a restart S3's 412 is the authority.
        self._last_sha: dict[str, str] = {}

    def _feed_dir(self, feed: str) -> Path:
        if feed not in FEEDS:
            raise ValueError(f"unknown feed {feed!r}; expected one of {sorted(FEEDS)}")
        directory = self.root / feed
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def write_snapshot(self, snap: Snapshot) -> SpoolResult:
        """Store a snapshot atomically, or skip it if it repeats the previous one for its feed."""
        directory = self._feed_dir(snap.feed)
        key = object_key(snap)
        if self._last_sha.get(snap.feed) == snap.sha256:
            return SpoolResult("duplicate", None, key)

        final = directory / spool_name(snap)
        tmp = final.with_name(final.name + TMP_SUFFIX)
        with tmp.open("wb") as f:
            f.write(snap.gz)
            f.flush()
            os.fsync(f.fileno())  # bytes on disk before the name becomes visible
        os.replace(tmp, final)  # atomic: readers see the whole file or nothing
        _fsync_dir(directory)

        self._last_sha[snap.feed] = snap.sha256  # only after the write succeeded
        return SpoolResult("written", final, key)

    def pending(self) -> list[Path]:
        """Complete snapshot files not yet uploaded, oldest first (by cut time, then feed)."""
        files = [
            path
            for feed in sorted(FEEDS)
            if (self.root / feed).is_dir()
            for path in (self.root / feed).iterdir()
            if path.name.endswith(EXTENSION) and not self.is_uploaded(path)
        ]
        return sorted(files, key=lambda p: (p.name, p.parent.name))

    @staticmethod
    def is_uploaded(path: Path) -> bool:
        return path.with_name(path.name + UPLOADED_SUFFIX).exists()

    @staticmethod
    def mark_uploaded(path: Path) -> None:
        path.with_name(path.name + UPLOADED_SUFFIX).touch()

    def remove_stale_tmp(self, now: float, older_than_s: float = 3600) -> int:
        """Delete temp files left by a crash. Only spool files, never anything in S3."""
        removed = 0
        for feed in sorted(FEEDS):
            directory = self.root / feed
            if not directory.is_dir():
                continue
            for path in directory.glob("*" + TMP_SUFFIX):
                if now - path.stat().st_mtime > older_than_s:
                    path.unlink(missing_ok=True)
                    removed += 1
        return removed
