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
- **Would change if:** Metro throttles long connections, or a Swiftly key arrives and this stream proves unreliable.
- **Record:** ADR-021; `docs/research/day1-probe.md`.

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
- **The DST detail:** the next run is built from tomorrow's local date at 03:00, not "last run plus 24 hours". Otherwise it would drift to 02:00 or 04:00 after a clock change.
- **Rejected:** downloading on a fixed 24-hour timer (drifts); polling hourly with full downloads (22 MB each for a file that changes about weekly). Conditional requests (`ETag`, `304`) are the upgrade if same-day freshness ever matters.
- **Record:** `docs/spec/01-data-pipeline.md` sections 2.3 and 4; quiz 018.

### 9. Watching the watcher: an external heartbeat

- **Decision:** after each good cut, ping an external heartbeat service, but only while every feed is healthy. `/healthz` on localhost reports per-feed health.
- **Why:** if the VM dies, any alerting that runs on it dies too. An outside service notices when the pings stop. Gating on every feed means a dead trip-updates stream stops the pings even while vehicle positions look fine.
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
- **Why full SHAs:** a moving tag like `main` makes rollback ambiguous ("previous" would mean whatever `main` points to now). The deploy tool accepts only `^[0-9a-f]{40}$`, because the value is put into a shell command that runs as root on the VM. That allow-list blocks command injection. (Known nit: the code uses `re.match` with `$`, which also accepts a trailing newline. It isn't exploitable, but `fullmatch` is stricter; a fix is queued.)
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
- **Record:** ADR-001 decision 5; `docs/spec/01-data-pipeline.md`. (Claude writes this in M1 with property-based tests, ADR-022.)

### 15. Never join on `trip_id` directly; use a crosswalk

- **Decision:** link sources through a crosswalk keyed on `(trip_id, service_date, schedule_version)`. Try an exact match first, then a fallback on route, direction and start time, and count whatever stays unmatched.
- **Why:** Metro's trip IDs embed a service-change tag, so every ID changes at each service change. A direct join breaks overnight, and the misses look like fake missed trips. The match rate is a tracked metric.
- **Record:** ADR-001 decision 4.

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
