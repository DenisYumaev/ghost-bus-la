"""Turn a stream of WebSocket frames into snapshots on a fixed time grid.

A snapshot is the latest frame for every entity (vehicle or trip) seen since the previous cut,
one frame per line, byte-for-byte as received, sorted by entity ID, gzip-compressed with a fixed
header. Identical content therefore gives identical bytes, hash, and file (ADR-021 decision 2).

A snapshot is complete only if the connection stayed up for the whole interval (ADR-021
decision 4, from the measured loop timing in docs/research/ws-cycle-timing.md).

Everything here is pure: callers pass in times and frames, so tests use a fake clock and no
network. Parsing is limited to reading `id` and the entity timestamp; stored bytes are never
re-serialized.
"""

import base64
import gzip
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Literal

GZIP_LEVEL = 6
_EPSILON_S = 1e-6


def next_grid_point(now: float, interval_s: int) -> float:
    """The first multiple of `interval_s` (seconds since the Unix epoch) strictly after `now`.

    Cuts land on the wall-clock grid (:00 and :30 for 30 s), and a late cut never shifts the
    schedule: the next point is computed from the clock, not from the previous cut plus a delay.
    """
    return float((math.floor(now / interval_s) + 1) * interval_s)


def entity_key(raw: bytes) -> tuple[str, int | None, bool]:
    """Return (key, newest entity timestamp, whether the frame had an `id`).

    A frame that isn't a JSON object with an `id` is never dropped: it gets the key
    `_noid:<sha256 of its bytes>`, which can't collide with a real ID, so identical frames
    collapse to one line and different ones are all kept.
    """
    try:
        message = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        message = None
    if not isinstance(message, dict) or "id" not in message:
        return "_noid:" + hashlib.sha256(raw).hexdigest(), None, False

    timestamp = None
    for entity_field in ("vehicle", "tripUpdate"):
        body = message.get(entity_field)
        if isinstance(body, dict) and "timestamp" in body:
            try:
                timestamp = int(body["timestamp"])
            except (TypeError, ValueError):
                timestamp = None
    return str(message["id"]), timestamp, True


def _line(raw: bytes) -> tuple[bytes, bool]:
    """The snapshot line for a frame, and whether it had to be wrapped.

    A frame containing a newline would break one-frame-per-line framing. None were seen in about
    74,000 recorded frames, but if one arrives it's stored base64-encoded, which is reversible.
    """
    if b"\n" in raw or b"\r" in raw:
        wrapped = json.dumps({"_unframed_b64": base64.b64encode(raw).decode("ascii")})
        return wrapped.encode(), True
    return raw, False


@dataclass(frozen=True)
class Snapshot:
    feed: str
    cut_at: float
    interval_s: int
    data: bytes  # uncompressed: sorted lines, each ending in a newline
    gz: bytes
    sha256: str
    n_entities: int
    n_messages: int
    n_unkeyed: int  # frames received without an `id` (not distinct lines)
    n_unframed: int
    newest_entity_ts: int | None
    connected_s: float
    partial: bool

    @property
    def sha16(self) -> str:
        return self.sha256[:16]


@dataclass(frozen=True)
class EmptyCut:
    """Nothing to write: the connection was down all interval, or the server sent nothing."""

    feed: str
    cut_at: float
    interval_s: int
    connected_s: float
    reason: Literal["disconnected", "no_messages"]


class SnapshotBuffer:
    """Latest frame per entity since the last cut, plus how long the connection was up."""

    def __init__(self, feed: str, interval_s: int, interval_start: float) -> None:
        self.feed = feed
        self.interval_s = interval_s
        self._interval_start = interval_start
        self._latest: dict[str, bytes] = {}
        self._n_messages = 0
        self._n_unkeyed = 0
        self._newest_ts: int | None = None
        self._connected_since: float | None = None
        self._connected_s = 0.0

    def on_connect(self, at: float) -> None:
        if self._connected_since is None:
            self._connected_since = at

    def on_disconnect(self, at: float) -> None:
        if self._connected_since is not None:
            self._connected_s += at - max(self._connected_since, self._interval_start)
            self._connected_since = None

    def on_message(self, raw: bytes, at: float) -> None:
        key, timestamp, keyed = entity_key(raw)
        self._latest[key] = raw
        self._n_messages += 1
        if not keyed:
            self._n_unkeyed += 1
        if timestamp is not None and (self._newest_ts is None or timestamp > self._newest_ts):
            self._newest_ts = timestamp

    def cut(self, at: float) -> Snapshot | EmptyCut:
        """Close the interval ending at `at` and start the next one."""
        if at < self._interval_start:
            raise ValueError(f"cut at {at} is before the interval start {self._interval_start}")

        connected_s = self._connected_s
        if self._connected_since is not None:
            connected_s += at - max(self._connected_since, self._interval_start)
        partial = connected_s < (at - self._interval_start) - _EPSILON_S

        result: Snapshot | EmptyCut
        if not self._latest:
            reason: Literal["disconnected", "no_messages"] = (
                "disconnected" if connected_s <= 0 else "no_messages"
            )
            result = EmptyCut(self.feed, at, self.interval_s, connected_s, reason)
        else:
            lines = [_line(self._latest[key]) for key in sorted(self._latest)]
            data = b"".join(line + b"\n" for line, _ in lines)
            result = Snapshot(
                feed=self.feed,
                cut_at=at,
                interval_s=self.interval_s,
                data=data,
                gz=gzip.compress(data, compresslevel=GZIP_LEVEL, mtime=0),
                sha256=hashlib.sha256(data).hexdigest(),
                n_entities=len(lines),
                n_messages=self._n_messages,
                n_unkeyed=self._n_unkeyed,
                n_unframed=sum(wrapped for _, wrapped in lines),
                newest_entity_ts=self._newest_ts,
                connected_s=connected_s,
                partial=partial,
            )

        self._reset(at)
        return result

    def _reset(self, at: float) -> None:
        self._interval_start = at
        self._latest = {}
        self._n_messages = 0
        self._n_unkeyed = 0
        self._newest_ts = None
        self._connected_s = 0.0
        # A connection that is still up carries over; its time now counts from `at`.
