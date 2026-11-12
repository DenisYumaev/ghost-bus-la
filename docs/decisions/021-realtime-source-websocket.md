# ADR-021: Realtime source is the Metro API WebSocket; cancellations come from trip updates

- **Status:** Proposed. Accepted in M0's closing PR, once one full day of snapshot sizes has been measured and decision 3's cadences are final. Until then, ingest is built on decisions 1, 2, and 4 to 7 as written here
- **Date:** 2026-11-12
- **Supersedes:** ADR-001 decisions 1 and 3 (on acceptance)
- **Evidence:** `docs/research/day1-probe.md`, run 2026-11-11

## Context

ADR-001 assumed HTTP polling of the Metro API: its realtime endpoints every 30 seconds and its canceled-service endpoint every 60 seconds. The day-1 probe found:

- The REST realtime endpoints (`/LACMTA/trip_detail/...`) return `[]` while buses are running.
- The canceled-service API was last updated 2022-10-04, and its detail endpoints return HTTP 500.
- The WebSocket streams `wss://api.metro.net/ws/LACMTA/vehicle_positions` and `wss://api.metro.net/ws/LACMTA/trip_updates` are live and need no key. The server sends one JSON message per entity (vehicle or trip) and loops over the whole fleet every 3 to 4 seconds. There is no feed header and no marker for the end of a loop.
- Trip updates mark trips `scheduleRelationship: "CANCELED"`, for both today's and tomorrow's service dates, and keep them in the stream after the trip's start time.
- Measured cycle sizes: about 0.46 MB for vehicle positions and 3.5 MB for trip updates, uncompressed.

## Decision

1. **Source.** Archive both WebSocket streams, all routes, with one long-lived connection per stream and never more. Realtime data is not polled over HTTP. The Metro API's REST realtime, canceled-service, and static endpoints are not used.

2. **Snapshots.** For each stream, ingest keeps the latest message per entity ID in memory and cuts a snapshot on a fixed grid (`next = start + n × interval`). A snapshot is the latest message for every entity seen since the previous cut, one message per line, byte-for-byte as received, sorted by entity ID, compressed with gzip using a fixed header so that identical content gives identical files.

   *Clarifies ADR-001 decision 2.* A WebSocket has no single "response" to store. Here "raw" means each message's bytes are unchanged. Which messages a snapshot contains and in what order is our framing; it is deterministic and defined in this decision.

3. **Cadence (provisional).** `vehicle_positions` every 30 seconds, `trip_updates` every 60 seconds. These are starting points. One full day of M0 data sets the final values, and the measured daily volume, raw and compressed, is recorded here before this ADR is accepted.

   | Feed | Snapshot every | Uncompressed per day (from probe cycle sizes) | Compressed per day |
   | --- | --- | --- | --- |
   | `vehicle_positions` | 30 s | about 1.3 GB | measured in M0 |
   | `trip_updates` | 60 s | about 5 GB | measured in M0 |

4. **Completeness.** If the connection was down for the whole interval, write nothing and log `network_error`. If it was down for part of the interval, write what arrived and log `partial = true`. The stream has no end-of-loop marker, so how a full cycle is detected is an open design item, settled and tested in the snapshot PR and then recorded in `docs/spec/01-data-pipeline.md` section 2.3.

5. **Announced cancellations** are trip-update messages with `tripUpdate.trip.scheduleRelationship == "CANCELED"`, identified by `(tripId, startDate)`. An entry disappearing from the stream is not evidence of anything: canceled entries linger after the trip's time, so events close by time, not by absence (`docs/spec/03-alerts.md`).

6. **Schedule** comes only from `gtfs_bus.zip` in the LACMTA GitLab repo, and a new version is detected by file hash. The Metro API's own schedule endpoints hold an older version than the live stream.

7. **Second source.** A Swiftly GTFS-realtime API key is requested in M0, as a fallback and a cross-check. No code is written against it unless this source fails.

## Why

Metro's realtime data only shows what's happening right now, so if I'm not recording, that history is gone. The only source that worked without a key was a WebSocket, so I chose to archive from it right away instead of waiting for a better one. Every 30 seconds for vehicle positions and every 60 seconds for trip updates, I save a snapshot: the latest message from each vehicle or trip seen since the last one, stored exactly as Metro sent it, so I can fix parser bugs later by re-reading the raw files. I treated the snapshot frequency as provisional until I'd measured a full day of real sizes, because that decides the storage bill.

## Alternatives considered

- **Wait for a Swiftly key before archiving.** A cleaner, documented GTFS-realtime feed, but it takes days to arrive and every day of waiting loses history that can't be recovered.
- **Write every message to disk as it arrives.** Nothing is lost between cuts, but the volume is about 20 times larger (the server re-sends the fleet every 3 to 4 seconds), and every downstream reader would have to rebuild snapshots itself.
- **Filter the stream to Metro-operated routes.** Smaller, but irreversible. ADR-001 decision 7 stands: ingest every line, scope headline metrics later.
- **Several connections per stream, split by route, for resilience.** Undocumented limits on someone else's server make this a risk with no measured benefit.

## Consequences

- `trip_updates` is the critical stream: the alerts and the M1 advance-notice gate depend on it, and it is about 85% of the raw volume.
- The fetch log's `http_status` is `null` for WebSocket feeds. Each disconnect is logged with its close code. The example in `docs/spec/01-data-pipeline.md` section 2.5, with a `.pb` key and HTTP status 200, predates this ADR and is corrected in the ingest PRs.
- Expected S3 writes at these cadences are about 4,320 a day (2,880 plus 1,440), before the GTFS download and hourly fetch-log files. Storage cost is recorded after the measured day.
- The local duplicate shortcut (`docs/spec/01-data-pipeline.md` section 2.4, step 2) will rarely fire on streams that change every few seconds. Content-addressed keys with conditional writes remain the real idempotency guarantee (ADR-004).
- Ingest identifies itself with `User-Agent: ghost-bus-la/<version> (+https://github.com/DenisYumaev/ghost-bus-la)`. The repository is the contact route; no personal email address is sent to Metro.
- If the stream changes shape, the raw bytes are still archived, and the schema-fingerprint check (pipeline spec, section 10) flags it.

## Would change if

- The server throttles or drops long-lived connections. Watch disconnects and close codes in the first 48 hours (SPEC section 10).
- Message shapes change in a way that breaks entity IDs or `startDate`.
- The measured compressed volume makes storage cost material against the $35 monthly target.
- A Swiftly key arrives and this WebSocket proves unreliable, in which case Swiftly becomes the primary source in a new ADR.
