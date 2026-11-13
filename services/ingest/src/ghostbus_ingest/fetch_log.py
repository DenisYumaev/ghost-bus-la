"""The fetch log: one JSON line per snapshot attempt and per connection event (spec 2.5).

It's what lets the pipeline tell an outage from a quiet feed (the `unknown` outcome), and it's
the source of the capture SLO. So every attempt is logged, success or failure, and each line is
flushed and fsynced before the next snapshot.

Files: <root>/_fetch_log/dt=YYYY-MM-DD/hour=HH.jsonl, by the UTC time of the event.
Events: `fetch` (a snapshot attempt), `connect`, `disconnect`; the uploader adds `upload`.
"""

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ghostbus_ingest.snapshot import EmptyCut, Snapshot
from ghostbus_ingest.spool import SpoolResult, object_key, spool_name

URL_KEY = "metro_ws"
UPLOADED_SUFFIX = ".uploaded"
_LOG_FILE = re.compile(r"dt=(\d{4}-\d{2}-\d{2})/hour=(\d{2})\.jsonl$")


def _hour_start(path: Path) -> datetime:
    match = _LOG_FILE.search(path.as_posix())
    if match is None:
        raise ValueError(f"not a fetch-log file: {path}")
    return datetime.strptime(f"{match[1]} {match[2]}", "%Y-%m-%d %H").replace(tzinfo=UTC)


def iso_utc(at: float) -> str:
    """`2026-11-13T02:14:30Z`, with milliseconds only when they aren't zero."""
    moment = datetime.fromtimestamp(at, tz=UTC)
    if moment.microsecond:
        return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class FetchLog:
    def __init__(self, root: Path, ingest_version: str) -> None:
        self.root = root
        self.ingest_version = ingest_version

    def path_for(self, at: float) -> Path:
        moment = datetime.fromtimestamp(at, tz=UTC)
        return self.root / "_fetch_log" / f"dt={moment:%Y-%m-%d}" / f"hour={moment:%H}.jsonl"

    def _append(self, at: float, record: dict[str, Any]) -> None:
        path = self.path_for(at)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def record_fetch(
        self, cut: Snapshot | EmptyCut, result: SpoolResult | None, error: str | None = None
    ) -> None:
        """Log one snapshot attempt.

        An EmptyCut is `network_error`. A Snapshot with no result and an error is `spool_error`
        (the write to disk failed, for example a full disk).
        """
        record: dict[str, Any] = {
            "event": "fetch",
            "fetched_at": iso_utc(cut.cut_at),
            "feed": cut.feed,
            "url_key": URL_KEY,
            "http_status": None,  # a WebSocket has no per-snapshot HTTP status (ADR-021)
            "latency_ms": None,
        }
        if isinstance(cut, Snapshot):
            record |= {
                "bytes": len(cut.data),
                "bytes_gz": len(cut.gz),
                "content_hash": cut.sha256,
                "object_key": object_key(cut),
                "spool_file": spool_name(cut) if result and result.path else None,
                "outcome": result.outcome if result else "spool_error",
                "feed_header_ts": (
                    iso_utc(cut.newest_entity_ts) if cut.newest_entity_ts is not None else None
                ),
                "n_entities": cut.n_entities,
                "n_messages": cut.n_messages,
                "n_unkeyed": cut.n_unkeyed,
                "n_unframed": cut.n_unframed,
                "partial": cut.partial,
                "error": error,
            }
        else:
            record |= {
                "bytes": None,
                "bytes_gz": None,
                "content_hash": None,
                "object_key": None,
                "spool_file": None,
                "outcome": "network_error",
                "feed_header_ts": None,
                "n_entities": 0,
                "n_messages": 0,
                "n_unkeyed": 0,
                "n_unframed": 0,
                "partial": True,
                "error": cut.reason,
            }
        record |= {
            "connected_s": round(cut.connected_s, 3),
            "interval_s": cut.interval_s,
            "ingest_version": self.ingest_version,
        }
        self._append(cut.cut_at, record)

    def record_connection(
        self,
        feed: str,
        event: Literal["connect", "disconnect", "connect_failed"],
        at: float,
        close_code: int | None = None,
        reason: str | None = None,
    ) -> None:
        self._append(
            at,
            {
                "event": event,
                "at": iso_utc(at),
                "feed": feed,
                "close_code": close_code,
                "reason": reason,
                "ingest_version": self.ingest_version,
            },
        )

    def record_upload(
        self,
        at: float,
        spool_file: str,
        object_key: str | None,
        outcome: Literal["written", "duplicate", "error", "corrupt"],
        error: str | None = None,
    ) -> None:
        """Log one spool-file upload attempt (fetch-log uploads are tracked by their markers)."""
        self._append(
            at,
            {
                "event": "upload",
                "at": iso_utc(at),
                "spool_file": spool_file,
                "object_key": object_key,
                "outcome": outcome,
                "error": error,
                "ingest_version": self.ingest_version,
            },
        )

    def files_to_upload(self, now: float, final: bool) -> list[tuple[Path, bytes, str]]:
        """Hourly files whose current content isn't in S3 yet: (path, bytes, sha256).

        Closed hours always; the still-open hour only on the final pass at shutdown. A file that
        grows after an upload (a restart mid-hour, a late line) is uploaded again under a new
        content-addressed key, and readers take the union (ADR-004).
        """
        result = []
        for path in sorted((self.root / "_fetch_log").glob("dt=*/hour=*.jsonl")):
            closed = _hour_start(path).timestamp() + 3600 <= now
            if not (closed or final):
                continue
            data = path.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            if self.uploaded_sha(path) != sha:
                result.append((path, data, sha))
        return result

    @staticmethod
    def object_key_for(path: Path, sha256: str) -> str:
        start = _hour_start(path)
        return f"bronze/_fetch_log/dt={start:%Y-%m-%d}/hour={start:%H}/{sha256[:16]}.jsonl"

    @staticmethod
    def uploaded_sha(path: Path) -> str | None:
        marker = path.with_name(path.name + UPLOADED_SUFFIX)
        return marker.read_text().strip() if marker.exists() else None

    @staticmethod
    def mark_uploaded(path: Path, sha256: str) -> None:
        path.with_name(path.name + UPLOADED_SUFFIX).write_text(sha256 + "\n")

    def clean_uploaded(self, now: float, keep_s: float) -> int:
        """Delete hourly files whose exact current content is in S3, once older than keep_s."""
        removed = 0
        for path in sorted((self.root / "_fetch_log").glob("dt=*/hour=*.jsonl")):
            hour_end = _hour_start(path).timestamp() + 3600
            if now - hour_end <= keep_s:
                continue
            if self.uploaded_sha(path) == hashlib.sha256(path.read_bytes()).hexdigest():
                path.unlink()
                path.with_name(path.name + UPLOADED_SUFFIX).unlink(missing_ok=True)
                removed += 1
        return removed
