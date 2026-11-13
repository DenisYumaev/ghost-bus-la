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
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ghostbus_ingest.snapshot import Snapshot

FEEDS = frozenset({"vehicle_positions", "trip_updates"})
EXTENSION = ".ndjson.gz"
UPLOADED_SUFFIX = ".uploaded"
TMP_SUFFIX = ".tmp"
CORRUPT_SUFFIX = ".corrupt"
_SPOOL_NAME = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{6})Z_([0-9a-f]{16})\.ndjson\.gz$")


def _utc(at: float) -> datetime:
    return datetime.fromtimestamp(at, tz=UTC)


def spool_name(snap: Snapshot) -> str:
    """`<cut time>_<sha16>.ndjson.gz`. The time prefix lets readers process files in order."""
    return f"{_utc(snap.cut_at):%Y%m%dT%H%M%SZ}_{snap.sha16}{EXTENSION}"


def object_key(snap: Snapshot) -> str:
    """The content-addressed S3 key (ADR-004). `dt` is the UTC fetch date, a storage partition."""
    return f"bronze/{snap.feed}/dt={_utc(snap.cut_at):%Y-%m-%d}/{snap.sha16}{EXTENSION}"


def parse_spool_name(path: Path) -> tuple[datetime, str]:
    """(cut time, sha16) from `<YYYYMMDDTHHMMSSZ>_<sha16>.ndjson.gz`."""
    match = _SPOOL_NAME.match(path.name)
    if match is None:
        raise ValueError(f"not a spool file name: {path.name!r}")
    year, month, day, hms, sha16 = match.groups()
    cut = datetime.strptime(f"{year}{month}{day}{hms}", "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    return cut, sha16


def spool_object_key(path: Path) -> str:
    """The S3 key for a spool file: the same key `object_key` gives for its snapshot."""
    cut, sha16 = parse_spool_name(path)
    feed = path.parent.name
    if feed not in FEEDS:
        raise ValueError(f"spool file name {path} is not under a known feed directory")
    return f"bronze/{feed}/dt={cut:%Y-%m-%d}/{sha16}{EXTENSION}"


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

    @staticmethod
    def set_aside_corrupt(path: Path) -> Path:
        """Rename a file whose bytes don't match its name, so it's kept but never uploaded."""
        target = path.with_name(path.name + CORRUPT_SUFFIX)
        os.replace(path, target)
        return target

    def clean_uploaded(self, now: float, keep_s: float) -> int:
        """Janitor (spec 2.4, step 5): delete spool files that are in S3 and older than keep_s.

        Never touches a file without an upload marker, and never anything in S3. (The detector
        cursor condition is added with the detector in M3.)
        """
        removed = 0
        for feed in sorted(FEEDS):
            directory = self.root / feed
            if not directory.is_dir():
                continue
            for path in directory.glob("*" + EXTENSION):
                cut, _sha16 = parse_spool_name(path)
                if self.is_uploaded(path) and now - cut.timestamp() > keep_s:
                    path.unlink()
                    path.with_name(path.name + UPLOADED_SUFFIX).unlink(missing_ok=True)
                    removed += 1
        return removed

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
