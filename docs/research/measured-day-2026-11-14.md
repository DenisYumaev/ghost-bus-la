# Measured day: 2026-11-14 (UTC)

The M0 task "measure a full day of snapshot sizes, raw and compressed, and set the cadences from them" (`docs/SPEC.md` M0; ADR-021 decision 3). Nov 14 is the first complete UTC day in the archive: ingest has run since 2026-11-13 05:54 UTC.

**Query:** `uv run python scripts/measure_day.py --bucket <data bucket> --date 2026-11-14`, run 2026-11-15. It reads the day's fetch log from `bronze/_fetch_log/dt=2026-11-14/` (24 hourly files) and aggregates every `fetch` line. Byte counts are for snapshots with outcome `written` (stored in the spool, then uploaded): `bytes` is the uncompressed snapshot, `bytes_gz` the stored object.

## Results

| Feed | Cuts expected | Attempted | Outcomes | Partial | Raw | Gzipped | Disconnects |
| --- | --- | --- | --- | --- | --- | --- | --- |
| vehicle_positions (30 s) | 2880 | 2880 (100.00%) | written 2880 | 1 | 1.176 GB | 129.5 MB | 1 |
| trip_updates (60 s) | 1440 | 1440 (100.00%) | network_error 4, written 1436 | 1 | 5.853 GB | 364.0 MB | 1 |

Total gzipped: **0.493 GB** for the day. Each stream disconnected once, and no reconnection attempt failed. "Partial" counts stored snapshots whose connection dropped for part of the interval (one per feed); each stored what arrived.

The four `network_error` cuts on trip updates all have reason `no_messages`: the connection was up, but Metro sent nothing for a whole minute. That's a server-side pause, not a dropped connection. The pipeline treats those minutes as `unknown`, not as missed trips (pipeline spec, section 2.5). Worth watching: if `no_messages` minutes grow, the stream may be stalling.

## Against the estimates

| | Estimate | Measured |
| --- | --- | --- |
| vehicle_positions, uncompressed | about 1.3 GB a day (probe cycle size, ADR-021) | 1.18 GB |
| trip_updates, uncompressed | about 5 GB a day (same) | 5.85 GB |
| Both feeds, gzipped | about 0.65 GB a day (`docs/research/ws-cycle-timing.md`) | 0.49 GB |
| Snapshots written | about 4,320 a day (ADR-021) | 4,316 (2,880 + 1,436) |

Compression is about 9× for vehicle positions and 16× for trip updates.

## Cost at these cadences

At S3 Standard list prices in us-west-2 ($0.023 per GB-month for storage; $0.005 per 1,000 PUT requests; check current pricing before quoting):

- **Storage** grows about 15 GB a month (0.49 GB × 30), so it costs about $0.35 a month after month one and adds about that much each month: about $4 a month after a year.
- **Requests:** about 130,000 snapshot PUTs a month (one per snapshot written), about $0.65. The fetch log (24 files a day) and the GTFS ZIP (a new 22 MB version about weekly) are negligible.

Both are small against the project's $35 monthly target (ADR-021 "Would change if").

## Decision

**Keep the provisional cadences: vehicle positions every 30 s, trip updates every 60 s.** The volume and cost leave no reason to cut them. Faster cuts aren't needed either: every entity reappears within 6.74 s, and a missed trip is absent for its whole run, not for seconds. ADR-021 is accepted with these values.

## M0 acceptance, first criterion

"24 hours of snapshots exist with at least 99% of scheduled polls attempted": **met.** 100% of scheduled cuts were attempted on both feeds. The second criterion (an hour's kill shows as a gap in the fetch log and the heartbeat alert fires) is drill 1, still to run.
