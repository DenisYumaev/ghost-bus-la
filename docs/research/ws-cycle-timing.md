# WebSocket loop timing and snapshot sizes

Measured on Thursday, November 12, 2026, at about 7:13 p.m. Pacific (03:13 UTC on Nov 13), from the owner's laptop. One 45-second connection per stream, using `scripts/record_ws.py`, analyzed with a one-off script. One evening's sample: the full measured day in M0 replaces the size numbers here.

**Purpose:** settle ADR-021's open item (how ingest knows a snapshot holds a full cycle) and get a first estimate of storage volume.

## Findings

| | `vehicle_positions` | `trip_updates` |
| --- | --- | --- |
| Frames in 45 s | 22,589 | 51,198 |
| Distinct entities | 1,647 | 3,948 |
| Frames that weren't JSON, or had no `id` | 0 | 0 |
| Top-level keys, every frame | `id`, `route_code`, `vehicle` | `id`, `route_code`, `tripUpdate` |
| Frame size, median / p99 / max | 444 / 474 / 476 bytes | 362 / 6,149 / 8,351 bytes |
| **Gap between appearances of the same entity**, median / p95 / max | 2.93 / 5.62 / **5.90 s** | 3.50 / 6.58 / **6.74 s** |
| Time from connect until 99% of entities were seen | 4.16 s | 3.21 s |
| Entities first seen more than 15 s after connect | 2 | 8 |
| Canceled trips in the stream | n/a | 41 |

- **On connect, the server sends nearly the whole fleet within about 4 seconds**, then keeps looping. No entity went more than 6.74 s between appearances.
- The few entities first seen late (after 15 s) are vehicles and trips **joining** the stream, not ones the loop skipped: once they appear, they repeat on the same cadence.
- Messages arrive as text frames, one entity per frame, as the day-1 probe found.

## Decision this supports: when a snapshot counts as complete

A snapshot is **complete** when the connection stayed up for the whole interval since the previous cut. It is **partial** when the connection was down for any part of it. The fetch log records `partial` and `connected_s`, the seconds connected during the interval.

Why this rule rather than detecting loop boundaries in the stream:

- The stream has no end-of-loop marker, so detecting a loop would mean guessing from entity order. That's fragile, and it would break silently if the server changed its order.
- The slowest measured reappearance (6.74 s) is well under the shortest interval (30 s), so an uninterrupted interval always contains at least four full loops.
- It's conservative. A reconnect 25 s before a cut still receives several loops, but is flagged partial anyway. Downstream then treats a missing entity as "not observed", not "gone", which is the safe error. `connected_s` keeps the detail if a later analysis wants to relax this.

## First estimate of snapshot sizes

Latest message per entity over a 30-second window, sorted, gzip level 6 with a fixed header:

| Feed | One snapshot, raw | One snapshot, gzip | Ratio | Per day at its cadence, gzip |
| --- | --- | --- | --- | --- |
| `vehicle_positions` (30 s) | 0.56 MB | 0.065 MB | 8.6× | 0.19 GB |
| `trip_updates` (60 s) | 4.86 MB | 0.322 MB | 15.1× | 0.46 GB |

That totals about 0.65 GB a day, or about 20 GB a month. At S3 Standard's roughly $0.023 per GB-month, each month of archive adds about $0.46 to the monthly bill. An evening sample isn't a day: the M0 measurement is the number that goes into ADR-021.

## Fixtures

`scripts/trim_ws_fixture.py` cut the recordings to 25 entities per stream, keeping every frame for those entities with its timing: `services/ingest/tests/fixtures/{vehicle_positions,trip_updates}_45s.jsonl.gz`, about 4 KB each. They include canceled trips, vehicles with no trip, and late joiners. `services/ingest/tests/test_ws_fixtures.py` fails if a re-trim loses any of these.
