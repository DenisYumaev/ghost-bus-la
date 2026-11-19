# Interview decisions

The trade-offs in Ghost Bus LA you should be able to defend out loud. Each entry gives the decision, why, the main alternative rejected, and what would change it, with a link to the full record. Claude adds or updates an entry in every PR that makes a decision (ADR-022).

**How to practise:** cover everything below a heading and explain it in 60 seconds. Then answer "what would you do at 100 times the scale?"

## Built

### 1. Archive first, before the product exists

- **Decision:** start recording Metro's realtime feeds on day 1, before any schedule, pipeline or UI work.
- **Why:** the realtime stream only shows the present. Every day not recorded is history you can never get back, and every reliability number depends on that history.
- **Rejected:** building the product first and archiving later. You lose the days you skip, for good.
- **Record:** ADR-001 context; `docs/SPEC.md` M0.

### 2. WebSocket snapshots as the realtime source

- **Decision:** keep one long-lived WebSocket connection per stream (vehicle positions, trip updates). Keep the latest message per vehicle or trip in memory, and cut a snapshot every 30 s (vehicles) or 60 s (trips).
- **Why:** the day-1 probe found Metro's REST realtime endpoints empty and its canceled-service API dead since 2022. The WebSocket is live and needs no key. The server re-sends the whole fleet every 3 to 4 s, so storing every message would be roughly 10 to 20 times the volume (a 30 or 60 s cut versus a 3 to 4 s loop) for no new information.
- **Rejected:** waiting for a Swiftly key (loses days of history); writing every message (10 to 20 times the volume, and every reader would have to rebuild snapshots); several connections per stream (undocumented limits on someone else's server).
- **Measured (2026-11-14):** 100% of scheduled cuts attempted (4 trip-update minutes came back empty because Metro sent nothing; they count as `unknown`, not missed); 0.49 GB a day gzipped across both feeds (raw is about 7 GB, so gzip saves 9 to 16×); about 15 GB of storage a month. The measurement set the cadences, not a guess.
- **Would change if:** Metro throttles long connections, or a Swiftly key arrives and this stream proves unreliable.
- **Record:** ADR-021; `docs/research/day1-probe.md`; `docs/research/measured-day-2026-11-14.md`.

### 3. Raw bytes in bronze, never parsed at ingest

- **Decision:** bronze stores each message exactly as received. Parsing happens downstream.
- **Why:** parsers have bugs. If you parse at ingest, a bug corrupts the data forever. With raw bytes you fix the parser and re-run over the full history. This is what makes "rebuild everything from bronze" true.
- **Rejected:** parsing to JSON or Parquet at ingest. It's easier to query on day 1, but it can't be undone.
- **Record:** ADR-001 decision 2; ADR-021 decision 2 (what "raw" means for a stream).

### 4. Content-addressed keys plus conditional writes for idempotency

- **Decision:** the S3 key is a hash of the content (`bronze/<feed>/dt=…/<sha16>.ndjson.gz`), written with `If-None-Match: *`. A `412` response means "already stored" and counts as success.
- **Why:** the same bytes always land on the same key, and S3 checks for an existing key and writes in one atomic step. A retry, a restart or a second writer can't create a duplicate or overwrite anything.
- **Rejected:** fetch time in the key with a list-before-write check. That's two requests, so two writers can both see nothing and both write: a race.
- **Know the edge case:** a 16-hex-character hash could in theory collide. At most 2,880 snapshots per feed per day (vehicle positions; trip updates is 1,440), the chance is at most about 2 in 10 trillion per day, and the full hash in the fetch log would reveal it.
- **Record:** ADR-004 decisions 1 and 2.

### 5. "Bronze is sacred" is enforced by AWS, not by code

- **Decision:** the bucket policy denies deletes on `bronze/*` and any write without `If-None-Match`, for every principal including admins. The bucket also has versioning and `prevent_destroy` in Terraform.
- **Why:** rules in a README don't stop a bug or a tired human at a terminal; a bucket policy does. Verified on 2026-11-12: an unconditional write to `selftest/`, covered by the same policy statement as `bronze/`, returned `403` even for an administrator. Deletes on `bronze/` weren't tested directly.
- **Rejected:** S3 Object Lock. It's stronger, but it can never be turned off once enabled.
- **Know the limit (an interviewer will probe this):** the deny policy stops bugs and accidents, not a determined admin. An administrator, and always the root user, can delete the bucket policy outside Terraform. That residual risk is accepted for a one-person project; if insiders were the threat, Object Lock in compliance mode is the answer.
- **Record:** ADR-004 decision 3 and its `VERIFY` results.

### 6. Spool to local disk first, then upload

- **Decision:** ingest writes each snapshot to a local spool, and a separate uploader thread sends it to S3. Local files get time-ordered names, while S3 keys use hashes.
- **Why:** an S3 outage must not lose data; the spool drains when S3 comes back (that's the M0 chaos drill). Spool files are written atomically: write to `.tmp`, `fsync` the file, rename, then `fsync` the directory. A crash therefore never leaves a half-written file that looks complete.
- **Why different names:** the spool needs time order (the detector processes oldest first), and two identical snapshots at different times must not overwrite each other. In S3, deduplication is the goal, so the key is the hash.
- **Rejected:** writing straight to S3. Simpler, but any S3 or network hiccup loses snapshots.
- **Proven (drill 2, 2026-11-16):** S3 blocked for about 10 minutes; 17 upload errors, 38 snapshots kept spooling, uploads resumed on the first retry after the block (9 s later), pending count 0 at the next check, nothing lost, no restart.
- **Record:** `docs/spec/01-data-pipeline.md` section 2.4; quizzes 010 and 012.

### 7. The uploader is paranoid about what counts as success

- **Decision:** only a `200` or a real `412` marks a file as uploaded. Before uploading, the uploader checks that a file's bytes match the hash in its name, and sets mismatches aside as `.corrupt`. Local files are deleted only after 48 hours, and only if they have an upload marker.
- **Why:** if an error such as `403` were ever misclassified as a duplicate, the janitor would delete files that never reached S3, while the fetch log said they were stored. That is silent, permanent data loss with a perfect-looking SLO. Treat every error class explicitly.
- **Record:** quizzes 011 and 012.

### 8. Completeness judged by connection uptime

- **Decision:** a snapshot is complete if the connection stayed up for the whole interval, and partial otherwise (`partial = true`, plus `connected_s` in the fetch log). Nothing is written if the connection was down for the whole interval.
- **Why:** the stream has no end-of-loop marker. Measurement showed every entity reappears within 6.74 s, well under the shortest interval of 30 s, so "connected the whole time" means "saw everything".
- **Why it matters downstream:** the fetch log lets the pipeline tell a feed outage from a quiet feed. That is what keeps an outage from being counted as missed trips.
- **Record:** ADR-021 decision 4; `docs/research/ws-cycle-timing.md`.

### 8a. The schedule download: store only new bytes, reject what isn't a ZIP

- **Decision:** fetch Metro's GTFS ZIP on start and daily at 03:00 Los Angeles time. Store it, byte for byte, only when its hash changes; each new hash is a schedule version. Refuse a body that isn't a ZIP, and wait a day instead of retrying on a permanent 4xx.
- **Why:** the hash is the only reliable version signal (Metro leaves `feed_version` empty). Bronze can never be deleted, so a stored HTML error page would become a permanent fake schedule version. Retrying a 404 every minute would hammer someone else's server for nothing.
- **It can't hurt the streams:** a bug in the download is logged and retried, never raised; the body is capped at 64 MB because it's held in memory under a 512 MB container limit; the 120 s timeout covers the whole request (httpx's timeout is per read, so a trickling server could otherwise hold it forever); and a stop signal cancels a download in flight, so a deploy restart stays fast.
- **Restarts don't duplicate:** the last stored hash is kept on disk. The S3 key includes the UTC date, so without it a restart on a new day would store the same 22 MB again, and bronze can't be deleted.
- **The DST detail:** the next run is built from tomorrow's local date at 03:00, not "last run plus 24 hours". Otherwise it would drift to 02:00 or 04:00 after a clock change.
- **Rejected:** downloading on a fixed 24-hour timer (drifts); polling hourly with full downloads (22 MB each for a file that changes about weekly). Conditional requests (`ETag`, `304`) are the upgrade if same-day freshness ever matters.
- **Record:** `docs/spec/01-data-pipeline.md` sections 2.3 and 4; quiz 018.

### 9. Watching the watcher: an external heartbeat

- **Decision:** after each good cut, ping an external heartbeat service, but only while every feed is healthy. `/healthz` on localhost reports per-feed health.
- **Why:** if the VM dies, any alerting that runs on it dies too. An outside service notices when the pings stop. Gating on every feed means a dead trip-updates stream stops the pings even while vehicle positions look fine.
- **Proven (drill 1, 2026-11-17):** ingest stopped gracefully for an hour; the DOWN email arrived about 4 minutes later (1-minute period plus 3 minutes' grace), the fetch log showed zero events for the hour, and the UP email came 2 s after the first cut on restart.
- **Record:** `docs/spec/01-data-pipeline.md` section 2.6; quiz 015.

### 10. Clean shutdown makes a final cut

- **Decision:** on SIGTERM, each stream makes a final cut, closes its socket cleanly, and the uploader makes a final pass, including the still-open fetch-log hour.
- **Why:** deploys restart the container. Without a final cut and upload, every deploy would lose up to one interval of data plus part of an hour of logs.
- **Record:** quiz 014.

### 11. One VM, SSM only, an instance role, no keys

- **Decision:** a single t4g.small with no inbound ports, reached only through SSM Session Manager. It uses an IAM instance role for short-lived credentials and requires IMDSv2.
- **Why:** about $33 a month all in, and one person can run and explain all of it. No SSH port to attack, and no long-lived keys to leak (an AWS key leaked on 2026-11-10, so this is a real story).
- **Rejected:** ECS or EKS (cost and complexity with no benefit at this load); serverless (a bad fit for a process that holds a connection open 24/7); access keys on the VM.
- **Would change if:** there's more than one API instance, or uptime needs beat what one VM can give. Then ECS behind a load balancer.
- **Record:** ADR-004 decision 5; SPEC decision register row 011.

### 12. Deploys: immutable SHA tags, health-gated, automatic rollback

- **Decision:** CI builds an image tagged with the full git SHA. The laptop deploy tool sends the deploy through SSM. The VM waits up to 180 s for Docker's health check to report healthy, records the SHA only if it's healthy, and otherwise rolls back to the previous good SHA.
- **Why full SHAs:** a moving tag like `main` makes rollback ambiguous ("previous" would mean whatever `main` points to now). The deploy tool accepts only exactly 40 lowercase hex characters, because the value is put into a shell command that runs as root on the VM. That allow-list blocks command injection. It uses `fullmatch`, because `re.match` with `$` also accepts a trailing newline (the review caught this; fixed in PR #22).
- **Rejected:** deploying a moving tag such as `main` or `latest`.
- **Record:** quizzes 016 and 017; `docs/runbook.md`.

### 13. Terraform with remote state, applies only after a reviewed plan

- **Decision:** a small bootstrap configuration creates the state bucket and keeps its own state locally. The main configuration uses S3 state with native lock files, so there's no DynamoDB table. Every `apply` follows a `plan` the owner has reviewed.
- **Why:** a bucket can't hold the state that creates it. Native S3 locking removes one resource. The resources the scrapped repo had created were imported into Terraform, not destroyed, so nothing was left unmanaged.
- **Record:** ADR-004 decision 6; `infra/bootstrap/`.

### 14. Times in UTC; service date by the GTFS rule

- **Decision:** store UTC. GTFS times count from "noon minus 12 hours" on the service date in `America/Los_Angeles`, and can pass 24:00. A trip at 25:10 on service date D runs at 01:10 local on D+1.
- **Why:** local time is ambiguous during the daylight-saving change (1:30 a.m. happens twice). Using the calendar date puts every after-midnight trip on the wrong day.
- **The DST trap:** on a clock-change day, "noon minus 12 hours" is 23:00 or 01:00, not midnight. So "seconds since local midnight" is wrong; compute from noon minus 12 hours.
- **How it's computed:** take local noon on the service date as a UTC instant, subtract 12 real hours, add the GTFS seconds. Everything after the first step is UTC arithmetic, so GTFS differences are real elapsed time: a 01:30–03:30 trip on spring-forward day takes 2 hours although the clock moves 3.
- **How it's proven:** 16 hand-checked cases in `tests/fixtures/dbt_seeds/gtfs_time_cases.csv`, including pre-03:00 times on both switch days and owl trips on the eve of each (25:30 on Oct 31 is the *first* 01:30 on Nov 1), plus Hypothesis properties with clock-change days mixed in deliberately (uniform dates hit one only about 2 days in 365). Two plausible wrong versions, "seconds since local midnight" and "wall clock with day rollover", each fail several tests. The CSV is shared so the dbt SQL version will be pinned to the same values.
- **Rejected:** a wall-clock conversion (`combine(date + h // 24, time(h % 24, …))`). It's right on 361 days a year, which is why it's easy to ship.
- **Record:** ADR-001 decision 5; `docs/spec/01-data-pipeline.md` section 5; `packages/ghostbus_core/src/ghostbus_core/service_date.py` (PR #25); quiz 021.

### 15. Never join on `trip_id` directly; use a crosswalk

- **Decision:** link sources through a crosswalk keyed on `(trip_id, service_date, schedule_version)`. Try an exact match first, then a fallback on route, direction and start time, and count whatever stays unmatched.
- **Why:** Metro's trip IDs embed a service-change tag, so every ID changes at each service change. A direct join breaks overnight, and the misses look like fake missed trips. The match rate is a tracked metric.
- **Record:** ADR-001 decision 4.

### 15a. Which schedule is in force: versions by content hash

- **Decision:** every GTFS ZIP with a new SHA-256 is a version. It's valid from the later of its `feed_start_date` and the Los Angeles date it was first seen, until the day before the next version's start. "Next" means by start date, not download order. Same-day ties go to the later sighting; the loser keeps a row with an empty range.
- **Why:** Metro's `feed_version` is empty, so the hash is the only reliable signal. Ordering by start date lets a service change published a week early wait for its date. Keeping superseded rows means anything already matched against them (an alert sent that morning) still resolves.
- **Known limits, recorded rather than guessed:** a revert to an older ZIP's exact bytes isn't detected, and a postponed service change still takes effect on its original date (SPEC section 10; the Dec 13 service change is the live test).
- **How it's proven:** hand-checked cases, plus a brute-force oracle property and a property that every hash gets exactly one row. The first draft's structure-only properties would have passed a function returning `[]`. A mutation to the UTC date fails two tests.
- **Loading it from bronze:** the bronze listing says which ZIPs exist; the earliest `written` fetch-log line says when each was first seen. A `duplicate` line's `object_key` is never used, because ingest builds it from the duplicate's own day, where nothing is stored (true of both duplicates in the real bucket). A ZIP with no `written` line stops the load instead of getting a guessed date, since that date decides the schedule in force. The pipeline's S3 wrapper refuses any write under `bronze/`, a second layer behind the bucket policy.
- **Record:** `docs/spec/01-data-pipeline.md` section 4; `packages/ghostbus_core/src/ghostbus_core/schedule_versions.py`; `pipeline/decode/src/ghostbus_decode/gtfs_versions.py`; quizzes 022 and 023.

### 15b. Schedule extraction: strict, refuse the whole version

- **Decision:** each GTFS version's tables become typed Parquet. Any value that doesn't match an exact pattern, a missing required column, a duplicate header, or a malformed row refuses the whole version, with an example. Realtime decode quarantines bad rows instead.
- **Why the difference:** a realtime row that's bad affects one observation. A schedule with gaps affects every trip resolved against it: a dropped stop time makes a real trip look missed. The previous version stays in force while a refused one is fixed.
- **Why exact patterns:** measured on DuckDB 2.0, `TRY_CAST('2.5' AS INTEGER)` is 3, `'1e2'` is 100, `'NaN'` is a valid DOUBLE, and with auto-detection a short CSV row makes the sniffer pick a different delimiter, while a row starting with `#` is dropped as a comment. All silent. Each case is now a test that fails without the fix.
- **Rebuildable:** `_SUCCESS` records the extractor version, so a stricter extractor redoes old versions rather than leaving a mix of schemas.
- **Record:** `docs/spec/01-data-pipeline.md` sections 3 and 4; `pipeline/decode/src/ghostbus_decode/gtfs_tables.py`; quiz 024.

### 15c. Compaction: rows from the fetch log, bounded files

- **Decision:** each closed UTC day's snapshots become Parquet files under `derived/compacted/`, one row per `written` or `duplicate` fetch, with the exact stored bytes. 200 snapshots per file.
- **Why rows come from the fetch log, not the bucket listing:** content addressing stores identical bytes once, but the same bytes cut at two times are two observations. Those minutes of coverage are what let the pipeline say `unknown` instead of `missed`. Fetches whose object never arrived are listed, not dropped.
- **Why bounded files:** measured, DuckDB 2.0's Parquet writer allocated one buffer the size of the whole BLOB column: 512 MiB for a day of trip updates, failing at a 512 MB limit whatever the row-group setting. Two hundred snapshots (or 64 MB) per file caps memory (peak 750 MB for the whole run, with downloads in flight) no matter how big a day gets.
- **Why a marker, not a glob:** each run writes a new `run=<id>/` folder, then `_SUCCESS` listing its files, then deletes older runs. A crash at any point leaves the previous marker pointing at a complete run, so a reader never sees a mixed or half-written day (the review found the in-place version could silently lose a row). The marker records missing fetch-log hours too, so an incomplete log is visible.
- **Proof:** Nov 14 compacted to 2,880 + 1,436 rows with 129.46 MB + 363.98 MB of payload, matching the measured-day report.
- **Record:** `docs/spec/01-data-pipeline.md` section 3; `pipeline/decode/src/ghostbus_decode/compact.py`; quiz 025.

### 15d. Decode: strict typing, quarantine, and what counts as schema drift

- **Decision:** decode is Python (one tested place): each frame is typed strictly (an integer must be a JSON integer, not `0.5` or `true`; coordinates finite and in range; timestamps epoch digits). A failing frame goes to `_quarantine` with a reason naming the field and its exact bytes. Unknown extra fields are tolerated and show up in the snapshot's schema fingerprint.
- **Why quarantine here but refuse for the schedule:** a bad realtime frame affects one observation of one vehicle; refusing a whole day of realtime data for one bad frame would create a day of `unknown` outcomes. A bad schedule row affects every trip matched against it (entry 15b).
- **What drift means, from data:** the plan said a new fingerprint triggers the drift alert. On Nov 14, 34 overnight trip-update snapshots had a different fingerprint only because an optional field was absent when few trips run. So drift is defined as a field path or type *not in the approved set*; absences don't count. Otherwise the alert would fire every night and be ignored.
- **Proof:** Nov 14 decoded to 3,331,689 vehicle rows and 42,417,214 trip-update rows, 0 quarantined; 563 distinct trips flagged `CANCELED`.
- **Record:** `docs/spec/01-data-pipeline.md` sections 3 and 10; `pipeline/decode/src/ghostbus_decode/{frames,decode}.py`; quiz 026.

### 15e. dbt reads a local, marker-filtered copy

- **Decision:** `make dbt-sync` copies only marker-listed files (decoded parts, fetch-log hours, extracted schedule versions) into a gitignored `data/`. dbt-duckdb builds there, with a thin `src_*` view over each external source.
- **Why:** a glob over S3 could read a half-written run. The local copy can be globbed safely, and DuckDB needs no S3 credentials. The views exist because dbt unit tests can't mock an external source.
- **Tested end to end:** `test_dbt.py` pushes a synthetic world through the real GTFS load, compaction, decode and sync, then runs `dbt build` with every grain, data and unit test, offline, in 2 seconds.
- **What real data caught on day one:** the G Line and J Line have no `route_short_name` (1,274 trips would have had no line). And a check query in a Los Angeles-time session shifted counts by 8 hours, which led to a rule: SQL converts time zones explicitly.
- **Record:** `docs/spec/01-data-pipeline.md` sections 5 and 6; `pipeline/dbt/`; quiz 027.

### 15f. Which report wins, and one state per fetch

- **Decision:** silver keeps one row per GTFS-rt *report* of a trip (`stg_trip_reports`). When one snapshot has two reports of the same trip, the newest by Metro's timestamp is the trip's state for that fetch. Cancellation history is that one state per fetch, ordered by fetch time. Advance notice runs from the start of the final cancellation episode.
- **Why, from data:** in 266 snapshots the two reports disagreed. In 227 of them the newer one was a cancellation without a vehicle, next to an older report still carrying the bus. "Prefer the report with a vehicle" would have hidden real cancellations. I first ordered raw reports by Metro's timestamp across fetches, expecting lingering cancellations to be stale. A VERIFY query showed the opposite: Metro re-stamps them every fetch (1,107 of 1,111). And with two live entities refreshing, raw ordering invented episodes: 5 of 11 "later final episodes" on Nov 15 were artifacts. One chosen state per fetch fixed both. The lesson: measure the assumption the rule depends on before trusting the rule.
- **What's left to the next layer:** the alerts spec withdraws a cancellation only while the trip's start is still ahead, which needs the schedule. Silver exposes `reinstated_at` and `int_trip_observations` applies the cutoff (4 of 121 reinstatements on Nov 15 came after the start).
- **Record:** `docs/research/duplicate-trip-reports.md`; `pipeline/dbt/models/staging/stg_trip_reports.sql`, `stg_cancellations.sql`; quiz 028.

### 15g. Schedule expansion, checked two ways

- **Decision:** `int_schedule_expanded` lists every trip that should run on each service date: the version in force, then `calendar` (weekday flag within its dates), plus `calendar_dates` additions, minus removals; first and last stop times converted with the noon-minus-12-hours rule.
- **How it's proven:** the SQL time macro is tested against the same 16 hand-checked cases as the Python rule (one CSV, used as a dbt seed). A mutation to a midnight anchor fails 10 of them. The day's count was re-derived independently in plain Python from the raw GTFS (`scripts/check_schedule_expansion.py`): 9,534 trips on Sunday 2026-11-15 in both.
- **Scope:** only service dates the local copy covers completely (`_sync.json`), because the UTC days around the range are partial.
- **Record:** `pipeline/dbt/models/intermediate/`, `pipeline/dbt/macros/gtfs_to_utc.sql`; quiz 029.

### 15h. Observations: what counts as "seen running"

- **Decision:** a scheduled trip is observed running if, inside its window (start −30 min to end +60 min), a vehicle position with a SCHEDULED descriptor matched it through the crosswalk, or a chosen SCHEDULED trip update carried a vehicle. Furthest progress comes from vehicle positions, not trip-update predictions. A cancellation counts only if not withdrawn before the scheduled start.
- **Why each piece:** trip updates predict the *remaining* stops, so their maximum stop sequence is always near the end; only positions show progress. Non-chosen duplicate reports can be stale vehicle assignments next to a newer cancellation. The alerts spec withdraws a cancellation only while the start is still ahead.
- **What data showed** (`docs/research/observations.md`): on Nov 15, 121 trips were both "observed" and canceled. Most were mid-trip cancellations: 76 had positions after the start, with median progress 0.21 of the route, and 84 of the 88 with positions were canceled after the last one. Twelve only waited before departure. Calling them `ran` would be wrong, so outcomes need the coverage rule (`partial`) from day one.
- **A correction worth remembering:** my first write-up said "117 canceled after the last position, median coverage 0.15". The reviewer noticed 121/117 matched an unrelated pair (the reinstatement counts) and that 0.15 didn't fit "first stop". A committed script showed the real breakdown. Ad-hoc numbers in docs are how wrong stories survive, hence hard rule 11.
- **Record:** `pipeline/dbt/models/intermediate/int_trip_crosswalk.sql`, `int_trip_observations.sql`; quiz 030.

### 15i. Outcomes v1: four labels, and the reconciliation identity

- **Decision (ADR-024):** every scheduled trip gets exactly one outcome, by section 8's table, first match wins: `ran` (observed, coverage ≥ 0.80), `partial` (observed, coverage below that or unknown), `unknown` (not observed and feeds healthy in under 90% of the trip's 5-minute buckets), `missed` (everything else). `likely_untracked` (block neighbours) waits for M4.
- **Why `partial` is in M1:** mid-trip cancellations would otherwise count as `ran` (76 of the 121 observed-and-canceled trips on Nov 15). **Why "observed" needs evidence after the scheduled start:** a bus waiting at the first stop in the 30 minutes before departure isn't running the trip; requiring a sighting after the start moved 25 trips from `partial` to `missed`. **Why updates-only trips are `partial`:** a vehicle was assigned but never reported a position, so claiming `ran` would overstate service, and `unknown` would misreport feed health.
- **The identity:** scheduled = ran + partial + missed + unknown for every service date, enforced by a dbt test. If a join drops or doubles a trip, the build fails.
- **M1 acceptance:** `scripts/line_day_summary.py 754 2026-11-15`: 110 scheduled, 105 ran, 4 partial, 1 missed (announced), reconciliation ok. The script exits non-zero on a mismatch or an empty line, so it can't report a false "ok". These are internal numbers: M1's `missed` still includes trips M4 may call `likely_untracked`, and nothing is quoted until M5 checks against Metro's report.
- **Record:** ADR-024; `pipeline/dbt/models/gold/`; quiz 031.

### 15j. Serving data: precomputed tables, swapped atomically

- **Decision (ADR-007):** the API reads only Postgres. The pipeline precomputes every number and `publish` swaps whole tables into the `serving` schema: load `__new`, validate, then rename it into place inside one transaction.
- **Who owns which schema:** `publish` owns the serving table definitions. Serving tables hold no history (each load rebuilds them from gold), so a migration chain has nothing to preserve, and keeping the DDL next to the query that fills it means a column change is one code change. Alembic owns the durable schemas (`ops` now, `app` from M3), where rows must survive deploys.
- **Why not query DuckDB from the API:** DuckDB is a batch engine. Building one service date reads about 137 million decoded rows from three UTC days, and sync plus the build take about 4 minutes (drill 3). The API needs an indexed lookup over a small table, even while the files are being rebuilt.
- **Rejected:**
  - Alembic defines the tables and `publish` copies them with `LIKE`: every column change becomes a migration plus a code change, deployed in lockstep.
  - Truncate-and-insert: `TRUNCATE` locks the table, so API reads wait for the whole load; `DELETE` instead leaves dead rows after every publish.
  - Materialized views: the raw outcomes would have to live in Postgres too.
- **Roles:** `pipeline` creates, and so owns, the serving tables; only the owner can rename them during the swap. Grants vanish with each new table, so `api`'s read access comes from default privileges.
- **Constraints carry the rules:** `ops.publish_run` can't record a success without a row count, or a failure without an error. `ops.feed_status` can't be written by `ingest`, which keeps hard rule 3 visible in the schema. Each rule has a test against a real Postgres 16.
- **Record:** ADR-007; `services/api/src/ghostbus_api/alembic/versions/0001_serving_and_ops.py`; quiz 033.

### 15k. Reliability cells: day type from the schedule, windows from the data

- **Decision:** `fct_reliability` has one row per line × direction × day type × local hour × window (`28d`, `90d`, `all`), with the section 8 rates. `n_trips` = scheduled − unknown, because a trip we couldn't see is neither ran nor missed.
- **Day type from the schedule, not the calendar:** Metro runs Sunday service on holidays. The 2026 schedule adds its `…_Sunday` service IDs on Thanksgiving. Counting Thanksgiving as a weekday would mix Sunday operations into weekday cells. So each date takes the weekly pattern most of its scheduled trips come from.
- **Windows end at the data, not the clock:** the last service date with outcomes anchors every window, so rebuilding the same data gives the same table (drill 3) and a backfill is reproducible.
- **Suppression (ADR-025):** a cell with fewer than 30 trips publishes counts but no rate, and so does one with too few service days: 10 for weekdays, 4 for weekends. A rate from three trips is noise presented as a fact. Ten weekend days can never fit in a 28-day window, so a single 10-day rule would have hidden every weekend number in the default view. The owner chose 4, with bootstrap intervals showing the extra uncertainty.
- **Checked:** dbt tests confirm every trip is counted once in the `all` window, the counts in each cell add up, and windows nest. On real data (Nov 15 only) every cell is suppressed, as expected with one service date.
- **Holidays, from evidence:** the schedule removes the weekday services and adds Sunday ones on Thanksgiving and Labor Day (`docs/research/holiday-service.md`).
- **Record:** ADR-025; `pipeline/dbt/models/gold/fct_reliability.sql`, `int_service_day_types.sql`; quiz 034.

### 15l. Line tables: headsigns from stop headsigns, stop order from position

- **Decision:** three line tables, built for every schedule version ever in force: `dim_line`, `dim_line_direction` (headsign, main pattern) and `dim_line_stop` (every stop served, in order). The API serves the version in force on the rider's own date, so commute validation is right across a service change. A first draft used only the last synced day's version: a backfill or a new schedule would then have accepted removed stops, whose alerts never fire, and rejected new ones.
- **Headsigns:** Metro's `trips.txt` leaves `trip_headsign` empty for all 33,614 trips, but every stop time carries `stop_headsign` ("754 - Vermont / Athens Station"). The headsign is the most common one at the trips' first stops, without the line prefix. On combined lines (`14/37`) the prefix says which sub-line runs that direction, so it stays.
- **Stop order:** a direction runs several stop patterns (branches, short turns). Main-pattern stops keep their index. Every other stop is interpolated between the main-pattern stops before and after it in its own trip, then averaged. A first draft averaged each trip's own 0..1 position, and review showed a peak short turn starting mid-route would drag a trunk stop ahead of earlier ones. A dbt test now checks that main-pattern stops stay in route order. Rejected: the main pattern only, which drops branch stops riders board at; a full pattern merge, which is complex for a stop picker.
- **Record:** `pipeline/dbt/models/gold/dim_line*.sql`; quiz 035.

### 15m. One set of trips behind every number

- **Decision:** the home-page summary, the weekly trend and the reliability grid all read the same `int_trip_cells` (each trip with its day type, local hour and Metro-operated scope) and the same `int_windows`. dbt tests check that the summary equals the sum of the grid in every window, and that the trend sums to the `all` window.
- **Why:** if the home page says one rate and a line page implies another, a reader trusts neither. Sharing the inputs makes agreement structural, and the tests make it checked.
- **Suppression (ADR-026):** line and system summaries need 30 trips and 10 service days, the stricter minimum, because headlines are what people quote. A trend week needs 30 trips and 4 service days. The first draft had no day floor for weeks, and review showed a single Monday could become a full-looking weekly point.
- **Line headlines live in dbt:** `fct_line_summary`, built from the same trips, so the API never pools cells or invents a suppression rule. Both directions are pooled, never averaged.
- **Record:** `pipeline/dbt/models/gold/fct_system_summary.sql`, `fct_line_trend.sql`; quiz 036.

### 15n. Bootstrap intervals in SQL

- **Decision (ADR-027):** the cluster bootstrap over service dates (2,000 replicates, 95% percentile) runs as three nightly dbt models in DuckDB, not as a Python job. Dates are redrawn within day-type strata, so a 28-day replicate always has 20 weekdays and 4 of each weekend day. Each replicate re-weights every cell's daily counts by how often its date was drawn, so cells, line summaries and the system summary come from the same resampled days in one pass.
- **Why resample days, not trips:** trips on one day share causes (an operator shortage, a freeway closure). Treating them as independent would make intervals too narrow. The "cluster" is the day.
- **Reproducible randomness, and a trap:** draws come from hashing fixed inputs, so a rebuild is identical. The first draft used `hash(seed, window, r, k) % n`. Review found, and a query confirmed, that DuckDB's multi-argument hash XORs the last argument in without a final mix. For 16, 32 or 64 dates, every replicate was then the same pattern relabelled: identical counts of distinct dates, standard deviation 0. `hash(hash(...))` fixes it, and a test checks the draw function's randomness for 13 sizes.
- **Scale, measured:** at 90 days (858,000 trips) the replicate step is 75 million rows in 62–68 s and the percentiles 20–24 s on a laptop (`scripts/bench_bootstrap.py`). A first version using DuckDB's `quantile_cont` ran out of memory at 3 GB because it can't spill. Ranking and interpolating can spill; `--check` matched `quantile_cont` on 25,236 keys to 1.1 × 10⁻¹⁶ at 5 days. Peak memory was 4.2 GB, so a VERIFY in pipeline spec section 11 requires measuring the VM and a container memory cap before M4.
- **No interval at 0:** a percentile bootstrap of a rate that is 0 on every day gives [0, 0]. Publishing that would claim certainty, so no interval is shown at 0, or at a share of 0 or 1.
- **Rejected:** numpy (not on the stack); pure Python (hours); the delta method (poor near 0 with few days, exactly the weekend cells).
- **Record:** ADR-027; quiz 037.

### 16. Ingest every line; scope the headline numbers

- **Decision:** archive all lines, and compute headline metrics on Metro-operated lines only.
- **Why:** filtering later is cheap and reversible; not archiving is neither. Metro's own report excludes contracted lines, so including them would compare unlike things.
- **Record:** ADR-001 decision 7.

### 17. Tools only on evidence (no Kafka, no Redis, no Kubernetes)

- **Decision:** any tool outside the stack list needs an ADR naming the measured problem it solves.
- **Why:** every tool adds operations, cost and something to explain. "Why didn't you use Kafka?" is a likely question. The answer: one producer and a few consumers on one VM, at this volume, don't need a broker. A Postgres outbox gives the delivery guarantees.
- **Record:** ADR-003 decision 4.

### 18. SLOs with an error budget

- **Decision:** capture SLO of 99.5% of minutes per feed per month (216 minutes of budget). If the budget is spent, feature work stops.
- **Why:** "it runs" is a claim; a met SLO is evidence. 99.9% would allow 43 minutes a month, which one bad in-place deploy on one VM could use up.
- **Record:** ADR-003 decision 2.

## Planned (decided, not built yet)

One line each for now; each gets a full entry when its PR lands. Source: `docs/SPEC.md` section 5.

| Decision | Short why | Rejected |
| --- | --- | --- |
| Hot path (alerts) separate from batch path (stats) | Alerts need seconds; stats need correctness | One pipeline: alert latency tied to batch runtime |
| Transactional outbox, at-least-once plus idempotency keys | Correct under crashes without a broker | Email sent inline (lost or duplicated on a crash); Kafka or SQS for one consumer |
| Postgres serves precomputed aggregates; atomic table swap | Fast reads; the API never sees a half-loaded table | API queries Parquet directly |
| DuckDB and dbt on Parquet, no warehouse | Free and fast at this size; same SQL moves to a warehouse later | Snowflake or BigQuery: cost |
| cron first, Airflow in M4 | Feel the need (retries, backfills) before adopting the tool | Airflow from day one |
| Passwordless email links, server-side sessions | No passwords to leak; sessions can be revoked | Passwords; OAuth only; JWTs (can't revoke) |
| Verification by POST from a page | Email scanners follow GET links and burn one-time tokens | Plain GET link |
| Postgres on the VM with nightly dumps | RDS roughly doubles the bill | RDS |
| In-process cache plus HTTP caching, no Redis | Data changes at most every 10 minutes; one API instance | Redis |
| No staging environment | Cost; one engineer | Full staging stack |
| Micro-batch missed-trip detector first, streaming only on evidence | A tool must beat a measured baseline | Redpanda from the start |
