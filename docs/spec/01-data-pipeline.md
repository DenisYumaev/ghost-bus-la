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

These cadences are starting points. Uncompressed, they come to about 1.3 GB a day for positions and 5 GB a day for trip updates. Measure a full day, raw and compressed, in M0, then fix the cadences and record the cost in ADR-021.

### 2.3 Stream behavior

- One process. Each stream has its own connection and keeps, in memory, the latest message per entity ID.
- **Cutting a snapshot:** on a fixed grid (`next = start + n × interval`), write the latest message for every entity seen since the previous cut, one JSON message per line, exactly as received, sorted by entity ID. An entity that stopped appearing is absent from the next snapshot, which is how a vehicle or trip leaving the stream is recorded.
- **A snapshot is complete only if the connection stayed up for the whole interval** since the previous cut. Every entity reappears at least every 6.74 s (`docs/research/ws-cycle-timing.md`), so an uninterrupted 30 s interval holds at least four full loops. If the connection was down for the whole interval, write nothing and log `network_error`. If it was down for part of it, write what arrived and log `partial = true`. Either way, log `connected_s`, the seconds connected during the interval.
- **Reconnect** with exponential backoff (1 s, 2 s, 4 s, capped at 60 s) and jitter. Log every disconnect with its close code. Send a `User-Agent` naming the project and a contact address.
- One connection per stream, never more. This is someone else's server with undocumented limits.
- The GTFS download uses plain HTTPS with a 120 s timeout and the same backoff.

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

For `fetch` lines, `outcome` is `written` (stored in the spool), `duplicate` (the local shortcut: same bytes as the feed's previous snapshot), `network_error` (nothing to write: the connection was down all interval, or the server sent nothing; `error` says which), or `spool_error` (a snapshot existed but writing it to disk failed, for example a full disk; the stream keeps running). `http_status` and `latency_ms` are `null` for WebSocket feeds (ADR-021); `http_error` is reserved for the GTFS download. The fetch time lives here, not in the object key.

Written to `<spool>/_fetch_log/dt=YYYY-MM-DD/hour=HH.jsonl`, uploaded when the hour closes and on shutdown. Each upload is content-addressed, `bronze/_fetch_log/dt=YYYY-MM-DD/hour=HH/<sha16>.jsonl`, because a mid-hour restart uploads the same hour twice with different content and a fixed name would be rejected by the conditional write (ADR-004). Readers take the union of an hour's files and drop duplicate lines. `feed_header_ts` is the newest entity timestamp in the snapshot, because the stream has no feed header. The log also records `n_entities`, `partial`, and each disconnect.

The fetch log is what makes the `unknown` outcome possible. Without a record of failed fetches, an outage looks like a quiet feed.

### 2.6 Watching the watcher

- Ping an external heartbeat service after each successful cycle of the 30 s feeds. If the VM dies, in-pipeline alerts die with it; the external check doesn't.
- Expose `/healthz` on a local port: healthy if every feed succeeded within three of its intervals.
- Alert when spool disk usage passes 70%.

### 2.7 Tests

Recorded fixtures for each feed; duplicate suppression, both the local shortcut and a `412` from S3; atomic write (kill between write and rename leaves no visible file); reconnect and backoff after a dropped connection; a snapshot holds exactly the latest message per entity; a partial interval is logged as partial; uploader resumes after S3 failure; grid scheduling under a fake clock. Tests use a local fake WebSocket server replaying recorded messages.

## 3. Bronze, compaction, decode

| Layer | Location | Content | Mutability |
| --- | --- | --- | --- |
| Bronze raw | `bronze/<feed>/dt=…/<sha16>.<ext>` | Exact bytes | Append-only; the bucket policy denies deletes |
| Compacted | `derived/compacted/<feed>/dt=…/part-0.parquet` | One row per snapshot: `content_hash`, `object_key`, `fetched_at` (from the fetch log), `payload` (exact bytes) | Rebuildable; rewritten per UTC day |
| Decoded | `derived/decoded/<table>/dt=…/part-0.parquet` | Typed, flattened rows | Rebuildable; rewritten per UTC day |

**Compaction** (nightly for closed UTC days, and every 10 minutes for the open day into a separate `_open` partition): thousands of small objects become one Parquet file per feed per UTC day. The originals stay in `bronze/` forever and are never moved to a colder storage class, because per-object transition fees would exceed the saving (ADR-004).

**Decode** is Python, so that parsing and validation live in one tested place. Each stream has an adapter behind one interface, selected by file extension. Today that is one newline-delimited JSON adapter; a protobuf adapter is added only if Swiftly becomes a source. Decode never drops a record: rows that fail validation go to `derived/decoded/_quarantine/` with the reason.

Decoded tables:

- `vehicle_position`: `fetched_at, feed_ts, snapshot_sha, vehicle_id, trip_id, route_id, direction_id, start_date, start_time, lat, lon, bearing, speed, current_stop_sequence, stop_id, current_status, vehicle_ts`
- `trip_update`: `fetched_at, feed_ts, snapshot_sha, trip_id, route_id, direction_id, start_date, start_time, trip_schedule_relationship, vehicle_id, stop_sequence, stop_id, arrival_ts, departure_ts, stop_schedule_relationship`
- There is no separate cancellation table. A cancellation is a `trip_update` row whose `trip_schedule_relationship` is `CANCELED`; such rows carry no stop-time updates.
- `schema_fingerprint`: per snapshot, a hash of sorted field names and types. A new fingerprint for a feed triggers the schema-drift alert (section 10).

## 4. GTFS static and schedule versions

- Every downloaded ZIP with a new file hash is a **schedule version**. Store the ZIP in bronze and extract its tables to `derived/decoded/gtfs/<version>/…`.
- `dim_schedule_version`: `version_id` (hash prefix), `first_seen_at`, `feed_start_date`, `feed_end_date` (from `feed_info.txt` when present), `valid_from`, `valid_to`.
- `valid_from` = the later of `feed_start_date` and the date first seen. `valid_to` = the day before the next version's `valid_from`. The version in force for service date D is the one whose range contains D.
- Weekly `calendar_dates.txt` updates produce new versions with the same trip IDs; service changes produce new trip IDs. Both are handled by the same rule: always resolve trip IDs against the version in force.
- Never overwrite or delete a version.

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
- Tests must cover: a trip past 24:00; the March 2027 spring-forward date; a fall-back date; a trip that spans midnight UTC.

## 6. dbt models

Engine: dbt-duckdb reading Parquet from S3. Materialize silver and gold as Parquet partitioned by service date; rebuild whole partitions with overwrite, never append.

### 6.1 Silver

| Model | Grain | Key points |
| --- | --- | --- |
| `stg_vehicle_positions` | vehicle × `vehicle_ts` | Dedupe on (`vehicle_id`, `vehicle_ts`); quarantine impossible coordinates; attach service date |
| `stg_trip_updates` | trip × stop × `feed_ts` | Keep history; expose latest prediction per stop |
| `stg_cancellations` | trip × service date | From trip updates marked `CANCELED`: `first_seen_at`, `last_seen_at`, `n_snapshots`, and whether the trip later returned to `SCHEDULED` |
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

**Schema drift:** when a feed's fingerprint changes, keep landing raw data, raise an alert, and mark that feed's decode as `needs_review`. Downstream models for that feed pause until a person approves the new shape in `config/approved_schemas.toml`. The detector on the hot path fails closed the same way (alerts spec).

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
