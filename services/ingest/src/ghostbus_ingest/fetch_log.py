"""The fetch log: one JSON line per snapshot attempt and per connection event (spec 2.5).

It's what lets the pipeline tell an outage from a quiet feed (the `unknown` outcome), and it's
the source of the capture SLO. So every attempt is logged, success or failure, and each line is
flushed and fsynced before the next snapshot.

Files: <root>/_fetch_log/dt=YYYY-MM-DD/hour=HH.jsonl, by the UTC time of the event.
Events: `fetch` (a snapshot attempt), `connect`, `disconnect`; the uploader adds `upload`.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ghostbus_ingest.snapshot import EmptyCut, Snapshot
from ghostbus_ingest.spool import SpoolResult, object_key, spool_name

URL_KEY = "metro_ws"


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

    def record_fetch(self, cut: Snapshot | EmptyCut, result: SpoolResult | None) -> None:
        """Log one snapshot attempt. An EmptyCut is logged as `network_error`."""
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
                "outcome": result.outcome if result else "written",
                "feed_header_ts": (
                    iso_utc(cut.newest_entity_ts) if cut.newest_entity_ts is not None else None
                ),
                "n_entities": cut.n_entities,
                "n_messages": cut.n_messages,
                "n_unkeyed": cut.n_unkeyed,
                "n_unframed": cut.n_unframed,
                "partial": cut.partial,
                "error": None,
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
        event: Literal["connect", "disconnect"],
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
