# 01 · Data pipeline

Covers everything from Metro's feeds to the tables the API reads. ADR-001 holds the ingestion decisions, and ADR-004 (written in M0) records the storage design in sections 2.4 and 3. This file is the build detail.

**Principle:** only bronze is precious. Every table downstream must be rebuildable from bronze alone, with no network calls.

## 1. Sources

| Source | What it gives | Upstream refresh | Notes |
| --- | --- | --- | --- |
| Vehicle positions | Where each bus is and which trip it claims, with `startDate` | WebSocket `wss://api.metro.net/ws/LACMTA/vehicle_positions`; the whole fleet is re-sent every few seconds | JSON, one message per vehicle; about 1,500 vehicles, 0.46 MB per cycle |
| Trip updates | Predictions per stop; trips marked `CANCELED`; stops marked `SKIPPED` | WebSocket `wss://api.metro.net/ws/LACMTA/trip_updates` | JSON, one message per trip; about 3,250 trips covering today and tomorrow, 3.5 MB per cycle. **This is the source of announced cancellations** |
| ~~Canceled-service API~~ | Not used | | Dead: last updated 2022-10-04, detail endpoints return 500 |
| ~~REST realtime endpoints~~ | Not used | | Return empty lists |
| GTFS static (bus) | Routes, trips, blocks, stops, stop times, calendars | `calendar_dates.txt` weekly; full schedule at service changes | `https://gitlab.com/LACMTA/gtfs_bus/raw/master/gtfs_bus.zip` |
| Transitland archive | Past schedule versions | As published | Only needed if a version was missed |
| Metro monthly cancellation report | Percent of trips canceled per line | Monthly | Validation target |

Contracted lines, per Metro's cancellation-report page: 96, 125, 128, 130, 167, 177, 205, 218, 232, 256, 266, 501, 577, 603, 605. Ten of them are in the schedule and nine showed live vehicles in the probe. Keep this list as a dbt seed (`seed_contracted_lines.csv`) with `valid_from`/`valid_to`. Ingest every line; headline metrics and the comparison with Metro's monthly report use Metro-operated lines only.

Measured message shapes, counts, and sizes are in `docs/research/day1-probe.md`. Put URLs in `config/feeds.toml`, never in code. Never use the Metro API's own static endpoints; they hold an older schedule than the live stream.

## 2. Ingest service

### 2.1 Contract

`ingest` depends on the network, local disk, and S3, and on nothing else. It never imports application code and never needs Postgres. If S3 is unreachable it keeps spooling to disk.

### 2.2 Feeds and cadence (`config/feeds.toml`)

| Feed key | Transport | Snapshot every | Extension |
| --- | --- | --- | --- |
| `vehicle_positions` | WebSocket, one long-lived connection | 30 s | `ndjson.gz` |
| `trip_updates` | WebSocket, one long-lived connection | 60 s | `ndjson.gz` |
| `gtfs_static` | HTTPS download; daily 03:00 America/Los_Angeles, plus on start | on hash change | `zip` |

These cadences are final (ADR-021, accepted 2026-11-15). Measured on 2026-11-14: 1.18 GB uncompressed and 129.5 MB gzipped a day for positions, 5.85 GB and 364.0 MB for trip updates (`docs/research/measured-day-2026-11-14.md`; rerun with `scripts/measure_day.py`).

### 2.3 Stream behavior

- One process. Each stream has its own connection and keeps, in memory, the latest message per entity ID.
- **Cutting a snapshot:** on a fixed grid (`next = start + n × interval`), write the latest message for every entity seen since the previous cut, one JSON message per line, exactly as received, sorted by entity ID. An entity that stopped appearing is absent from the next snapshot, which is how a vehicle or trip leaving the stream is recorded.
- **A snapshot is complete only if the connection stayed up for the whole interval** since the previous cut. Every entity reappears at least every 6.74 s (`docs/research/ws-cycle-timing.md`), so an uninterrupted 30 s interval holds at least four full loops. If the connection was down for the whole interval, write nothing and log `network_error`. If it was down for part of it, write what arrived and log `partial = true`. Either way, log `connected_s`, the seconds connected during the interval.
- **Reconnect** with exponential backoff (1 s, 2 s, 4 s, capped at 60 s) and jitter. Log every disconnect with its close code. Send a `User-Agent` naming the project and a contact address.
- One connection per stream, never more. This is someone else's server with undocumented limits.
- The GTFS download uses plain HTTPS with a 120 s timeout and the same backoff, configured in `config/feeds.toml` under `[gtfs_static]`. It runs on start and daily at 03:00 Los Angeles time, computed from the local date so daylight-saving changes don't shift it. The 120 s is a limit on the whole request, not on each read. Network errors, 5xx, 429, and bodies that aren't a ZIP are retried with backoff, at most 10 times in a row; then, and on any other 4xx, the download waits for the next daily slot, because hammering someone else's server won't fix a moved file. A body that isn't a ZIP is never stored, since every stored hash becomes a schedule version (section 4). Bodies over 64 MB are refused (by `Content-Length` when sent, otherwise as soon as the cap is passed), since the body is held in memory under the container's 512 MB limit. The last stored hash is kept in `<spool>/gtfs_static/last_sha256`, so a restart doesn't store the same ZIP again under a new date. A GTFS failure, even a bug, never stops the streams. Implemented in `services/ingest/src/ghostbus_ingest/gtfs.py`.

### 2.4 Storing a snapshot (ADR-004)

1. Compute `sha256` of the snapshot's uncompressed bytes. Compress with gzip using a fixed header (no timestamp), so identical content gives identical files.
2. If the hash equals the previous successful snapshot of that feed, log the fetch with outcome `duplicate` and store nothing. This is a local shortcut; S3 is the authority (step 4).
3. Otherwise write to the spool as `<spool>/<feed>/<fetched_at>_<sha16>.<ext>.tmp`, `fsync`, then rename to drop `.tmp`. Rename is atomic, so readers never see a partial file. The spool name carries the fetch time (`YYYYMMDDTHHMMSSZ`) so the detector can process files in order.
4. The uploader thread writes each spool file to the content-addressed key
   `s3://<bucket>/bronze/<feed>/dt=YYYY-MM-DD/<sha16>.<ext>`
   using `PutObject` with `If-None-Match: *`, where `dt` is the UTC fetch date. A `412 Precondition Failed` means those bytes are already stored; record `duplicate`, which counts as success. After a written or duplicate result it leaves a `.uploaded` marker.
5. A janitor deletes spool files that are uploaded, older than 48 hours, and behind the detector's cursor.

Before the first production run, verify conditional writes on the versioned bucket using a scratch `selftest/` prefix outside `bronze/`, so the deny-delete policy doesn't make the test objects permanent. **Verified 2026-11-12:** `412` on the second write, and an unconditional write denied by the bucket policy (ADR-004 results; rerun with `make selftest-s3`).

### 2.5 Fetch log

One JSON line per snapshot attempt, success or failure (`event: "fetch"`), and one per connection change (`event: "connect"`, `"disconnect"` with the close code, or `"connect_failed"` with the error). The uploader adds `event: "upload"` lines. Implemented in `services/ingest/src/ghostbus_ingest/fetch_log.py`.

```json
{"event":"fetch","fetched_at":"2026-11-13T02:14:30Z","feed":"vehicle_positions","url_key":"metro_ws",
 "http_status":null,"latency_ms":null,"bytes":561204,"bytes_gz":65102,"content_hash":"<sha256>",
 "object_key":"bronze/vehicle_positions/dt=2026-11-13/<sha16>.ndjson.gz",
 "spool_file":"20261113T021430Z_<sha16>.ndjson.gz","outcome":"written",
 "feed_header_ts":"2026-11-13T02:14:11Z","n_entities":1646,"n_messages":8211,"n_unkeyed":0,
 "n_unframed":0,"partial":false,"error":null,"connected_s":30.0,"interval_s":30,"ingest_version":"0.1.0"}
{"event":"disconnect","at":"2026-11-13T02:15:02.250Z","feed":"trip_updates","close_code":1006,
 "reason":"abnormal closure","ingest_version":"0.1.0"}
```

For `fetch` lines, `outcome` is `written` (stored in the spool), `duplicate` (the local shortcut: same bytes as the feed's previous snapshot), `network_error` (nothing to write: the connection was down all interval, or the server sent nothing; `error` says which), or `spool_error` (a snapshot existed but writing it to disk failed, for example a full disk; the stream keeps running). `http_status` and `latency_ms` are `null` for WebSocket feeds (ADR-021); `http_error` is reserved for the GTFS download, whose `fetch` lines carry `url_key: "gtfs_bus_gitlab"`, the HTTP status, latency, size, and hash, with stream-only fields (`partial`, `connected_s`, `n_entities`, …) null. The fetch time lives here, not in the object key.

Written to `<spool>/_fetch_log/dt=YYYY-MM-DD/hour=HH.jsonl`, uploaded when the hour closes and on shutdown. Each upload is content-addressed, `bronze/_fetch_log/dt=YYYY-MM-DD/hour=HH/<sha16>.jsonl`, because a mid-hour restart uploads the same hour twice with different content and a fixed name would be rejected by the conditional write (ADR-004). Readers take the union of an hour's files and drop duplicate lines. `feed_header_ts` is the newest entity timestamp in the snapshot, because the stream has no feed header. The log also records `n_entities`, `partial`, and each disconnect.

The fetch log is what makes the `unknown` outcome possible. Without a record of failed fetches, an outage looks like a quiet feed.

### 2.6 Watching the watcher

- Ping an external heartbeat service (Healthchecks.io) after each successful cut of the fastest feed, **but only while every feed is healthy** by the `/healthz` rule below. A dead trip-updates stream then stops the pings even if vehicle positions are fine. If the VM dies, in-pipeline alerts die with it; the external check doesn't. The ping URL is a secret: it lives in SSM Parameter Store at `/ghost-bus-la/heartbeat-url` and is never logged. A missing URL disables the heartbeat with a log line and never stops ingest.
- Expose `/healthz` on a local port (8081, localhost only): healthy if every feed had a `written` or `duplicate` cut within three of its intervals, with the service start time standing in until a feed's first success. Returns 200 or 503 with per-feed detail.
- Alert when spool disk usage passes 70%.

### 2.7 Tests

Recorded fixtures for each feed; duplicate suppression, both the local shortcut and a `412` from S3; atomic write (kill between write and rename leaves no visible file); reconnect and backoff after a dropped connection; a snapshot holds exactly the latest message per entity; a partial interval is logged as partial; uploader resumes after S3 failure; grid scheduling under a fake clock. Tests use a local fake WebSocket server replaying recorded messages.

## 3. Bronze, compaction, decode

| Layer | Location | Content | Mutability |
| --- | --- | --- | --- |
| Bronze raw | `bronze/<feed>/dt=…/<sha16>.<ext>` | Exact bytes | Append-only; the bucket policy denies deletes |
| Compacted | `derived/compacted/<feed>/dt=…/run=<id>/part-<n>.parquet`, listed by `dt=…/_SUCCESS` | One row per snapshot fetch (`written` or `duplicate`): `fetched_at` (from the fetch log), `outcome`, `content_hash`, `object_key`, `partial`, `n_entities`, `payload` (exact stored bytes). At most 200 snapshots or 64 MB per file. Readers follow the marker, never a glob | Rebuildable; each run writes a new `run=` folder, then the marker, then deletes older runs |
| Decoded | `derived/decoded/<table>/dt=…/run=<id>/part-<n>-<k>.parquet`; `schema_fingerprint` and `_quarantine` under `feed=<feed>/`; all listed by the main table's `dt=…/_SUCCESS` | Typed, flattened rows | Rebuildable; same run protocol as compaction |

**Compaction** (nightly for closed UTC days, and every 10 minutes for the open day into a separate `_open` partition): thousands of small objects become a few Parquet files per feed per UTC day (`make compact DAY=`; built in `ghostbus_decode.compact`, which lives in the decode package rather than a separate `pipeline/compact/` to keep one workspace member). Rows come from the fetch log: identical bytes cut at two times are stored once but are two observations. Each row's bytes are located by hash among that day's and the previous day's objects; a fetch whose object never reached S3 is listed in `_SUCCESS` as `missing_objects`. Files are bounded because DuckDB's Parquet writer allocated a buffer the size of the whole column (512 MiB for a day of trip updates). A crash mid-run leaves the previous marker pointing at its complete run. The marker also records the fetch-log hours present (a missing hour is visible, not silently short), lines read, and unparseable lines; a day can be compacted from 01:00 UTC the next day, after its last hour has uploaded. The `_open` partition isn't built yet. The originals stay in `bronze/` forever and are never moved to a colder storage class, because per-object transition fees would exceed the saving (ADR-004).

**Decode** is Python, so that parsing and validation live in one tested place. Each stream has an adapter behind one interface, selected by file extension. Today that is one newline-delimited JSON adapter; a protobuf adapter is added only if Swiftly becomes a source. Decode never drops a record: rows that fail validation go to `derived/decoded/_quarantine/` with the reason. (This applies to realtime decode. The GTFS schedule is the exception: a schedule with gaps would turn real trips into missed ones, so a version with any bad value is refused whole and the previous version stays in force; section 4.)

Decoded tables:

- `vehicle_position`: `fetched_at, feed_ts, snapshot_sha, vehicle_id, trip_id, route_id, direction_id, start_date, start_time, lat, lon, bearing, speed, current_stop_sequence, stop_id, current_status, vehicle_ts`
- `trip_update`: `fetched_at, feed_ts, snapshot_sha, trip_id, route_id, direction_id, start_date, start_time, trip_schedule_relationship, vehicle_id, stop_sequence, stop_id, arrival_ts, departure_ts, stop_schedule_relationship`
- There is no separate cancellation table. A cancellation is a `trip_update` row whose `trip_schedule_relationship` is `CANCELED`; such rows carry no stop-time updates.
- `schema_fingerprint`: per snapshot, a hash of the sorted set of field paths and JSON types. A different fingerprint alone is **not** drift: on Nov 14, 34 overnight trip-update snapshots (01:03–02:46 Los Angeles) had a different fingerprint only because an optional field was absent. Drift means a field path or type not in the approved set (section 10).
- Decode (`make decode DAY=`, `ghostbus_decode.decode` and `.frames`) writes `vehicle_position` (one row per vehicle frame), `trip_update` (one row per stop-time update; one row with null stop fields for a trip with none, such as a cancellation), `schema_fingerprint` and `_quarantine` (reason plus base64 of the exact frame), each under `run=<id>/` with a `_SUCCESS` listing the parts, the same protocol as compaction. Extra columns beyond the list above: `trip_schedule_relationship` on vehicle positions, `entity_ts` (the trip update's own timestamp) on trip updates. Integers are range-checked to their column types (`direction_id` 0 or 1), so an extreme value quarantines one frame instead of failing the day. Frames ingest wrapped as `_unframed_b64` are unwrapped; a blank frame is quarantined as `empty`. The marker records the compaction run it read. Nov 14: 3,331,689 vehicle rows and 42,417,214 trip-update rows, 0 quarantined.
- For dbt: `scheduleRelationship` is stored as sent, so NULL means GTFS-rt's default, `SCHEDULED` (`COALESCE` it). A `duplicate` fetch repeats its snapshot's rows with a new `fetched_at` and the same `feed_ts`, so silver grains use `fetched_at`. Not extracted (bronze keeps them; the fingerprint would show them): `arrival.delay`, `departure.delay`, `uncertainty`, `tripUpdate.delay`, `vehicle.label`, `occupancyStatus`, `congestionLevel`. None appear in Nov 14's fingerprints today.
- Decode peaks at about 850 MB (trip updates, Python plus DuckDB). It runs on the laptop for now; before it's scheduled on the VM (M4), run it in a container with its own memory cap so the OOM killer can never pick ingest (hard rule 3).

## 4. GTFS static and schedule versions

- Every downloaded ZIP with a new file hash is a **schedule version**. Store the ZIP in bronze and extract its tables to `derived/decoded/gtfs/<version>/…`.
- Extraction (`make gtfs-load`): `routes`, `trips`, `stops`, `stop_times`, `calendar`, `calendar_dates`, `feed_info` to `<table>.parquet`, every row stamped `schedule_version`. Columns stay text as published, except dates (`DATE`), small integer codes, coordinates (`DOUBLE`, range-checked), and the two stop times, which keep their text and gain `arrival_s`/`departure_s` (GTFS seconds; SQL checked against `ghostbus_core.service_date`). Strict: every value must match an exact pattern (DuckDB's casts alone accept `2.5` as integer 3 and `NaN` as a coordinate), the CSV reader runs with auto-detection off, and a missing required column, duplicate header or malformed row refuses the version. One refused version doesn't block others; the run exits non-zero. `_SUCCESS` is written last and records the extractor version: readers use only versions with a matching `_SUCCESS`, and a newer extractor re-extracts older ones (`--force` redoes all). `shapes.txt` and fares aren't extracted yet.
- `dim_schedule_version`: `version_id` (hash prefix), `first_seen_at`, `feed_start_date`, `feed_end_date` (from `feed_info.txt` when present), `valid_from`, `valid_to`.
- `valid_from` = the later of `feed_start_date` and the date first seen. `valid_to` = the day before the next version's `valid_from`. The version in force for service date D is the one whose range contains D.
- "Date first seen" is the America/Los_Angeles calendar date of `first_seen_at`, since `valid_from` is compared with service dates. "Next version" means next by `valid_from`, then by `first_seen_at`: a service change published early waits for its start date. A ZIP first seen mid-day replaces that day's version for the whole service date on the next rebuild.
- If two versions share a `valid_from`, the one seen last wins that day. The other keeps its row with an empty range (`valid_to` = `valid_from` − 1 day), so anything already matched against it still resolves. Code: `ghostbus_core.schedule_versions`.
- Weekly `calendar_dates.txt` updates produce new versions with the same trip IDs; service changes produce new trip IDs. Both are handled by the same rule: always resolve trip IDs against the version in force.
- Never overwrite or delete a version.
- `make gtfs-load` writes `dim_schedule_version` after extraction, resolved over the versions that loaded: a refused version gets no date range and the previous one stays in force. `make gtfs-versions` is a read-only preview. **Coverage:** the archive's first ZIP was seen 2026-11-15 (ingest's GTFS download shipped that day), so no version is in force for service dates before Nov 15, even though realtime data starts Nov 13; outcomes start at Nov 15.
- Versions are identified by `content_hash`, not by object key: the same ZIP can, rarely, sit under two `dt=` partitions. The loader takes the earliest `first_seen_at` per hash.
- The loader (`make gtfs-versions`) locates each ZIP from the bronze listing and dates it from its earliest `written` fetch-log line, never from a `duplicate` line (whose `object_key` names the duplicate's own day). A ZIP stored today or yesterday (UTC) with no `written` line yet is skipped as waiting: the fetch-log hour uploads only when the hour closes. An older ZIP with no `written` line stops the load rather than getting a guessed date.

Facts about Metro's schedule that the loader must handle (from the probe):

- `feed_version` is empty and the repo's README lags, so the file hash is the only reliable version signal.
- `trip_headsign` is empty on every trip. Take the rider-facing destination from `stop_headsign` or `destination_code` in `stop_times.txt`.
- Times run to 29:45, and a few rows have an hour without a leading zero. Parse times into seconds; never compare them as text.
- 713 trips have no `block_id`; block inference can't apply to them.
- Route short names aren't all numbers (`10/48`, "Dodger Stadium Express"). Treat the line identifier as a string everywhere.
- `stop_times.txt` is 307 MB unzipped, about 2.1 million rows. Load it with DuckDB, not row by row in Python.
- The current schedule ends on 2026-12-12, so the next version is expected to take effect on Dec 13.

## 5. Time rules (get these exactly right)

- All stored timestamps are UTC. Local time is a display concern, except for the two fields below.
- **Service date** is the GTFS operating day. GTFS times are measured from "noon minus 12 hours" on the service date in `America/Los_Angeles`, so times can exceed `24:00:00`. A trip at `25:10:00` on service date 2026-11-13 runs at 01:10 local time on 2026-11-14.
- Conversion: `utc_ts = local_noon(service_date, tz) − 12 h + gtfs_seconds`, then convert to UTC. Using noon makes days with a daylight-saving change come out right.
- Prefer `start_date` from the GTFS-rt trip descriptor as the service date. If absent, derive it from the schedule: the service date whose trip window (start −30 min to end +60 min) contains the observation.
- Partition silver and gold by **service date**, never by arrival time.
- SQL never relies on the session time zone: convert with `timezone('UTC', ts)` (or `'America/Los_Angeles'`) explicitly before formatting, truncating, or comparing with a date. A laptop's DuckDB session is Los Angeles, and a check run that way on 2026-11-17 shifted every count by 8 hours.
- Tests must cover: a trip past 24:00; the March 2027 spring-forward date; a fall-back date; a trip that spans midnight UTC.

## 6. dbt models

Engine: dbt-duckdb reading Parquet from S3. Materialize silver and gold as Parquet partitioned by service date; rebuild whole partitions with overwrite, never append.

**As built (M1, ADR-023):** `make dbt-sync START= END=` (`ghostbus_decode.sync`) copies the marker-listed decoded parts, fetch-log hours and extracted schedule versions for those service dates (UTC days `START-1..END+1`: the day before catches early cancellation notices, the day after the trips past midnight Los Angeles) into the gitignored `data/`, all or nothing (built in `data/.staging/` and swapped in when complete; a range with an undecoded UTC day is refused). `make dbt` builds a DuckDB file there (`pipeline/dbt/`). Models are DuckDB tables for now; publishing Parquet to S3 comes with serving (section 13). Each external source has a thin `src_*` view, because dbt unit tests can't mock an external source. `pipeline/decode/tests/test_dbt.py` runs `dbt build`, with every data and unit test, over a synthetic world pushed through the real Python steps, in Los Angeles session time. `stg_fetch_log`'s key is (feed, fetched_at): two different attempts at one instant can only come from two ingest processes at once, and the uniqueness test fails the build rather than picking one.

### 6.1 Silver

| Model | Grain | Key points |
| --- | --- | --- |
| `stg_vehicle_positions` | vehicle × `vehicle_ts` | Dedupe on (`vehicle_id`, `vehicle_ts`), first sighting by a total order, `n_snapshots` = distinct fetches, `n_trips` (warn if > 1); service date = the trip descriptor's `start_date` (a vehicle on a trip without one fails a test: the section 5 fallback isn't built). Decode checks coordinates are finite and in range, not in Los Angeles |
| `stg_trip_reports` | trip × service date × fetch × entity | One row per GTFS-rt report of a trip. `report_ts` = entity timestamp, else fetch time. `is_chosen`: the newest report per trip-fetch (then the one with a vehicle, then entity), because Metro sometimes publishes a trip twice in one snapshot (`docs/research/duplicate-trip-reports.md`). A table (about 5M rows a day) so consumers don't re-run windows over stop rows |
| `stg_trip_updates` | trip × stop × fetch (view) | Stop predictions of the chosen report only; grain on `fetched_at`, not `feed_ts` (section 3); `is_trip_level` marks a report with no stop-time updates. "Latest prediction per stop" is deferred: M1's outcomes don't use predictions |
| `stg_cancellations` | trip × service date | One state per fetch: the relationship of the report `stg_trip_reports` chose, ordered by fetch time (Metro re-stamps lingering cancellations every fetch; two live entities would otherwise interleave into fake episodes, `docs/research/duplicate-trip-reports.md`). `first_seen_at` = first fetch of the *final* cancellation episode (canceled → scheduled → canceled counts from the second); `first_ever_canceled_at` (any report); `last_seen_at`, `n_snapshots` (fetches whose state was CANCELED); `reinstated_at` = the first SCHEDULED fetch after the last CANCELED one. Only SCHEDULED ends an episode. Whether a reinstatement counts (only while the scheduled start is still ahead, alerts spec) is applied in `int_trip_observations`, which must also read only `is_chosen` reports for "observed running" and only service dates fully inside the synced range |
| `stg_fetch_log` | fetch attempt | Typed copy of the JSONL |
| `dim_routes`, `dim_stops`, `dim_trips`, `dim_stop_times`, `dim_calendar` | entity × schedule version | From each GTFS version |
| `seed_contracted_lines` | line × validity | Seed |

### 6.2 Intermediate

| Model | Grain | Purpose |
| --- | --- | --- |
| `int_schedule_expanded` | scheduled trip × service date | Every trip that should run: apply `calendar` and `calendar_dates` for the version in force. Columns: `trip_id, route_id, line, direction_id, block_id, first_stop_id, sched_start_utc, sched_end_utc, n_stops, schedule_version` |
| `int_trip_crosswalk` | realtime trip key × service date | Maps observed trips to scheduled trips with `match_method` (`exact`, `fuzzy`, `unmatched`) and `match_confidence` |
| `int_trip_observations` | scheduled trip × service date | `first_seen_utc, last_seen_utc, max_stop_sequence, vehicle_ids, n_positions, n_updates, rt_canceled` |
| `int_feed_health_5min` | feed × 5 minutes | Healthy if at least one successful fetch whose feed header is under 3 minutes old |
| `int_block_neighbors` | scheduled trip × service date | Previous and next trip on the same block and whether each was observed, and with which vehicle |

### 6.3 Gold

| Model | Grain | Answers |
| --- | --- | --- |
| `fct_trip_outcomes` | scheduled trip × service date | `outcome`, `announced`, `announce_source`, `advance_notice_s`, `stop_coverage`, `match_method`, `is_metro_operated` |
| `fct_stop_service` | scheduled trip × stop × service date (P1) | Whether the trip served each stop |
| `fct_reliability` | line × direction × day type × hour × window | Trip counts and rates with intervals; windows `28d`, `90d`, `all` |
| `fct_stop_reliability` | line × direction × stop × day type × hour × window (P1) | Same, at the stop |
| `fct_feed_health` | feed × 5 minutes | Freshness, fetch error rate, healthy flag |
| `fct_reconciliation_monthly` | line × month | This project's canceled rate, Metro's, the difference, an explanation field |
| `fct_system_summary` | window | Headline numbers for the home page |

`fct_trip_outcomes` is the heart. Every other gold table aggregates it, so every number agrees with every other.

## 7. Trip matching

1. **Exact:** `(trip_id, service_date)` against the schedule version in force. Metro's trip IDs embed a service-change tag, so IDs change at each service change; matching against the wrong version silently fails.
2. **Fuzzy (P1):** when the ID is missing or unknown, match on route, direction, and start time within ±10 minutes; choose the closest; break ties by the vehicle's block history. Record `match_confidence`.
3. **Unmatched:** keep the rows, count them, report them in feed health.

Track `match_rate` per feed per day. Alert under 95%. A sudden drop usually means a new schedule version wasn't loaded.

## 8. Outcome classification

**Definitions**

- **Observation window:** scheduled start −30 min to scheduled end +60 min.
- **Observed running:** at least one matched vehicle position, or at least one trip update carrying a vehicle ID with a trip-level relationship of `SCHEDULED`. A trip update marked `CANCELED` is not an observation; it sets `rt_canceled`.
- **Stop coverage:** furthest stop sequence reached divided by the trip's stop count.
- **Feed-healthy share:** share of 5-minute buckets in the window in which both realtime feeds were healthy.

**Decision table, evaluated top to bottom; first match wins**

| # | Condition | Outcome |
| --- | --- | --- |
| 1 | Observed running and coverage ≥ 0.80 | `ran` |
| 2 | Observed running and coverage < 0.80 | `partial` |
| 3 | Not observed and feed-healthy share < 0.90 | `unknown` |
| 4 | Not observed; previous and next trips on the block were both observed with the same vehicle | `likely_untracked` |
| 5 | Not observed (everything else) | `missed` |

Rule 3 comes before rule 4 because block evidence is unreliable during an outage. A trip observed running during an outage is still classified by rules 1 and 2. A block's first and last trips have only one neighbor, so rule 4 can't apply to them.

**Announcement**

- `announced = true` if `rt_canceled` is true: the trip was marked `CANCELED` in trip updates and wasn't returned to `SCHEDULED`. `announce_source` records the channel, so a second one can be added later.
- `advance_notice_s` = scheduled start minus `first_seen_at` of the announcement. It can be negative, when a trip is marked canceled after it should have left.

|  | Announced | Not announced |
| --- | --- | --- |
| `ran` | Announced but ran (reinstated, or a data error); report the count | Normal service |
| `missed` | Announced cancellation | **Unplanned missed trip: the headline metric** |

**Rates**

```text
missed_rate     = missed / (scheduled − unknown)
announced_rate  = (missed and announced) / (scheduled − unknown)
unplanned_rate  = (missed and not announced) / (scheduled − unknown)
unplanned_share = unplanned_rate / missed_rate
```

`likely_untracked` and `partial` are reported separately and never counted as missed.

**Thresholds are starting points.** Tune 0.80, 0.90, ±10 min, and the window against hand-checked trips, then freeze them in an ADR. Keep them in `dbt_project.yml` vars so a sensitivity run is one command.

## 9. Uncertainty

Trips on one day share causes (an operator shortage at one division), so they aren't independent and a Wilson interval would be too narrow. Use a **cluster bootstrap over service dates**: resample whole days with replacement, 2,000 replicates, fixed seed, 95% percentile interval. Runs nightly in Python (`analysis/bootstrap.py`) and writes interval columns into `fct_reliability`.

Suppress any cell with fewer than 30 trips or fewer than 10 service days: publish `suppressed = true` and no rate.

## 10. Data quality

**dbt tests (P0)**

- Uniqueness and not-null on every model's grain
- Reconciliation identity, every service date: `scheduled = ran + partial + likely_untracked + missed + unknown`
- Relationships: every outcome row has a schedule row; every stop exists in the version in force
- Accepted values on `outcome`, `match_method`, `announce_source`
- Freshness: newest bronze snapshot under 5 minutes old; newest gold partition under 20 minutes old
- `match_rate ≥ 0.95` per day (warn), `≥ 0.80` (error)

**dbt unit tests** for the hard models, with small inline fixtures: schedule expansion (a `calendar_dates` exception adds and removes service), service date for a 25:10 trip, each row of the decision table, announcement cross.

**Schema drift:** when a feed shows a field path or JSON type not in its approved set (a fingerprint change from an absent optional field doesn't count), keep landing raw data, raise an alert, and mark that feed's decode as `needs_review`. Downstream models for that feed pause until a person approves the new shape in `config/approved_schemas.toml`. The detector on the hot path fails closed the same way (alerts spec).

**Volume anomaly:** alert when vehicles in service fall outside the baseline for that hour and weekday (median ± 4 MAD over the past 4 weeks).

## 11. Schedule and runtime budgets

| Job | Cadence | Budget |
| --- | --- | --- |
| Open-day compact + decode | Every 10 minutes | 60 s |
| dbt build for open service dates (today, and yesterday until it closes) | Every 10 minutes | 90 s |
| Publish to Postgres | After each build | 30 s |
| Close a service date (3 hours after its last scheduled trip ends), final build | Daily | 5 min |
| Compaction of closed days, bootstrap, reconciliation, dataset export | Nightly | 20 min |
| GTFS static check | Daily | 2 min |

A lock file prevents overlapping runs. If a run exceeds twice its budget, alert.

**Late data:** rows arriving after a service date closes still land in bronze. A weekly job reports closed dates with new bronze rows; reprocess them with a backfill.

## 12. Backfill

```bash
make backfill START=2026-11-15 END=2026-11-20
```

Rebuilds decode, silver, gold, and serving for the range from bronze, with no network calls. Idempotent: running it twice gives byte-identical Parquet (sort rows; fix seeds). Record the runtime for a full-history backfill; it is an interview number.

## 13. Publish to serving

For each serving table: load into `serving.<table>__new`, validate (row count within 20% of the previous load unless `--force`, no null keys), then inside one transaction rename the live table to `__old`, rename `__new` to live, and drop `__old`. Readers see either the old table or the new one, never a partial load. Update `ops.publish_run` with table, row count, source partition, and duration.

Serving tables are listed in the API spec, section 7.

## 14. Validation before any number is published

- Hand-trace 20 `missed`, 20 `ran`, and 10 `likely_untracked` trips through raw bronze. Record each in `docs/validation/`.
- Reconcile monthly per-line rates with Metro's report. First learn what Metro's report counts. Explain every line that differs by more than 2 points.
- Show headline results at 0.70, 0.80, and 0.90 stop coverage. A finding that flips under a reasonable threshold isn't a finding.

## 15. Open dataset (P1)

Monthly release, versioned `YYYY-MM`:

- `trip_outcomes/` Parquet by month, `reliability.parquet`, `feed_health.parquet`
- `DATA_DICTIONARY.md`, `METHOD.md`, `CHANGELOG.md`
- Credit LA Metro as the data source, following its terms
- Reproducible with `make release VERSION=2027-01`
