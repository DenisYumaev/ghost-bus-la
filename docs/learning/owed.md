# Owed learning work

A study backlog, not a blocker. Since ADR-022 (2026-11-15), quizzes and "What I learned" notes are optional and gate neither merges nor milestones. Claude still adds a row with every new PR and ticks items off when they're done. For interview prep, start with `interview-decisions.md`.

**How to clear an item**

- **Quiz:** open the file from its link, write your answers under each question, tell Claude, and get graded (4 of 5 to pass).
- **What I learned:** write 3 to 5 sentences in the space below, in your own words. Claude copies it into the PR description.
- **Why rewrite:** no longer needed; Claude writes ADR "Why" sections (ADR-022). The column is kept for history.

All quizzes are in `docs/learning/quizzes/` on `main`. Take them whenever you have time. Quiz headers that say "You need 4 of 5 before M0 closes" predate ADR-022; they no longer apply.

## Status

| PR | Topic | Quiz | What I learned | Why rewrite | Applied to AWS |
| --- | --- | --- | --- | --- | --- |
| [#1](https://github.com/DenisYumaev/ghost-bus-la/pull/1) | ADR-021, realtime source | [ ] [001](quizzes/001-adr-021.md) | [ ] | [x] ADR-021 | n/a |
| [#2](https://github.com/DenisYumaev/ghost-bus-la/pull/2) | Repo scaffold | [ ] [002](quizzes/002-scaffold.md) | [ ] | n/a | n/a |
| [#3](https://github.com/DenisYumaev/ghost-bus-la/pull/3) | ADR-003 and ADR-004 | [ ] [003](quizzes/003-adr-003-004.md) | [ ] | n/a (ADR-022) | n/a |
| [#4](https://github.com/DenisYumaev/ghost-bus-la/pull/4) | Terraform state bucket | [ ] [004](quizzes/004-infra-bootstrap.md) | [ ] | n/a | Yes, 2026-11-12 |
| [#5](https://github.com/DenisYumaev/ghost-bus-la/pull/5) | Data bucket import, policy, budget | [ ] [005](quizzes/005-infra-data-bucket.md) | [ ] | n/a | Yes, 2026-11-12 |
| [#7](https://github.com/DenisYumaev/ghost-bus-la/pull/7) | VM, role, recovery alarms | [ ] [006](quizzes/006-infra-vm.md) | [ ] | n/a | Yes, 2026-11-12 |
| [#8](https://github.com/DenisYumaev/ghost-bus-la/pull/8) | Conditional-write self-test | [ ] [007](quizzes/007-selftest-conditional-writes.md) | [ ] | n/a | Ran against the real bucket, 2026-11-12 |
| [#9](https://github.com/DenisYumaev/ghost-bus-la/pull/9) | WebSocket fixtures and loop timing | [ ] [008](quizzes/008-ws-fixtures.md) | [ ] | n/a | n/a |
| [#10](https://github.com/DenisYumaev/ghost-bus-la/pull/10) | Snapshot core | [ ] [009](quizzes/009-ingest-snapshot.md) | [ ] | n/a | n/a |
| [#12](https://github.com/DenisYumaev/ghost-bus-la/pull/12) | Spool and fetch log | [ ] [010](quizzes/010-ingest-spool.md) | [ ] | n/a | n/a |
| [#13](https://github.com/DenisYumaev/ghost-bus-la/pull/13) | Shared S3 write and backoff | [ ] [011](quizzes/011-ingest-s3-backoff.md) | [ ] | n/a | n/a |
| [#14](https://github.com/DenisYumaev/ghost-bus-la/pull/14) | Uploader | [ ] [012](quizzes/012-ingest-uploader.md) | [ ] | n/a | n/a |
| [#15](https://github.com/DenisYumaev/ghost-bus-la/pull/15) | WebSocket stream runner | [ ] [013](quizzes/013-ingest-stream.md) | [ ] | n/a | n/a |
| [#16](https://github.com/DenisYumaev/ghost-bus-la/pull/16) | Service entry point | [ ] [014](quizzes/014-ingest-service.md) | [ ] | n/a | n/a |
| [#17](https://github.com/DenisYumaev/ghost-bus-la/pull/17) | Health check and heartbeat | [ ] [015](quizzes/015-ingest-health.md) | [ ] | n/a | n/a |
| [#18](https://github.com/DenisYumaev/ghost-bus-la/pull/18) | Docker image and CI build | [ ] [016](quizzes/016-ingest-image.md) | [ ] | n/a | n/a |
| [#19](https://github.com/DenisYumaev/ghost-bus-la/pull/19) | Deploy ingest to the VM | [ ] [017](quizzes/017-deploy-ingest.md) | [ ] | n/a | Yes, running since 2026-11-13 05:54 UTC |
| [#21](https://github.com/DenisYumaev/ghost-bus-la/pull/21) | GTFS schedule download | [ ] [018](quizzes/018-ingest-gtfs.md) | [ ] | n/a | Yes, 2026-11-15 (`7da9646`) |
| [#22](https://github.com/DenisYumaev/ghost-bus-la/pull/22) | Strict SHA check in the deploy tool | [ ] [019](quizzes/019-deploy-sha-fullmatch.md) | [ ] | n/a | n/a (laptop tool) |
| [#23](https://github.com/DenisYumaev/ghost-bus-la/pull/23) | Measured day; ADR-021 accepted | [ ] [020](quizzes/020-measured-day.md) | [ ] | n/a | n/a (docs and a read-only script) |
| [#25](https://github.com/DenisYumaev/ghost-bus-la/pull/25) | GTFS time and service-date math (M1 piece 1) | [ ] [021](quizzes/021-service-date.md) | [ ] | n/a | n/a |
| [#26](https://github.com/DenisYumaev/ghost-bus-la/pull/26) | Schedule-version rule (version in force) | [ ] [022](quizzes/022-schedule-versions.md) | [ ] | n/a | n/a |
| [#27](https://github.com/DenisYumaev/ghost-bus-la/pull/27) | Drill 1 record; M0 acceptance met | n/a (no code) | [ ] | n/a | Ran on the VM, 2026-11-17 |
| [#28](https://github.com/DenisYumaev/ghost-bus-la/pull/28) | GTFS loader part 1: `dim_schedule_version` from bronze | [ ] [023](quizzes/023-gtfs-versions-loader.md) | [ ] | n/a | Wrote `derived/decoded/gtfs/dim_schedule_version.parquet`, 2026-11-17 |
| [#29](https://github.com/DenisYumaev/ghost-bus-la/pull/29) | GTFS loader part 2: strict table extraction | [ ] [024](quizzes/024-gtfs-tables.md) | [ ] | n/a | Extracted to `derived/decoded/gtfs/cb1a2283abecc0af/`, 2026-11-17 |
| [#30](https://github.com/DenisYumaev/ghost-bus-la/pull/30) | Compaction | [ ] [025](quizzes/025-compaction.md) | [ ] | n/a | Compacted 2026-11-14 to `derived/compacted/`, 2026-11-17 |
| [#31](https://github.com/DenisYumaev/ghost-bus-la/pull/31) | Decode realtime frames to typed tables | [ ] [026](quizzes/026-decode.md) | [ ] | n/a | Decoded 2026-11-14 to `derived/decoded/`, 2026-11-17 |
| [#32](https://github.com/DenisYumaev/ghost-bus-la/pull/32) | dbt setup, sync, fetch log and schedule dims | [ ] [027](quizzes/027-dbt-setup.md) | [ ] | n/a | n/a (local build over synced Nov 14) |
| [#33](https://github.com/DenisYumaev/ghost-bus-la/pull/33) | Realtime silver: vehicle positions, trip reports and updates, cancellations | [ ] [028](quizzes/028-realtime-silver.md) | [ ] | n/a | n/a (local build) |
| [#34](https://github.com/DenisYumaev/ghost-bus-la/pull/34) | Schedule expansion (int_schedule_expanded) | [ ] [029](quizzes/029-schedule-expansion.md) | [ ] | n/a | n/a (local build) |
| [#35](https://github.com/DenisYumaev/ghost-bus-la/pull/35) | Trip crosswalk (exact) and observations | [ ] [030](quizzes/030-observations.md) | [ ] | n/a | n/a (local build) |
| [#36](https://github.com/DenisYumaev/ghost-bus-la/pull/36) | Feed health and trip outcomes v1 (ADR-024); M1 acceptance query | [ ] [031](quizzes/031-outcomes.md) | [ ] | n/a | n/a (local build) |
| [#37](https://github.com/DenisYumaev/ghost-bus-la/pull/37) | Drill 3: re-derive a day from bronze; outputs identical | [ ] [032](quizzes/032-rerun-day.md) | [ ] | n/a | n/a (local build) |
| [#38](https://github.com/DenisYumaev/ghost-bus-la/pull/38) | Postgres `serving` and `ops` schemas (ADR-007); integration tests | [ ] [033](quizzes/033-postgres-schemas.md) | [ ] | n/a | n/a (not deployed yet) |
| [#39](https://github.com/DenisYumaev/ghost-bus-la/pull/39) | `fct_reliability` and schedule-based day types | [ ] [034](quizzes/034-reliability.md) | [ ] | n/a | n/a (local build) |
| [#40](https://github.com/DenisYumaev/ghost-bus-la/pull/40) | Line tables: `dim_line`, `dim_line_direction`, `dim_line_stop` | [ ] [035](quizzes/035-line-tables.md) | [ ] | n/a | n/a (local build) |
| [#41](https://github.com/DenisYumaev/ghost-bus-la/pull/41) | System summary and weekly line trend; shared trip cells and windows | [ ] [036](quizzes/036-summary-trend.md) | [ ] | n/a | n/a (local build) |
| [#42](https://github.com/DenisYumaev/ghost-bus-la/pull/42) | Cluster bootstrap intervals in dbt (ADR-027) | [ ] [037](quizzes/037-bootstrap.md) | [ ] | n/a | n/a (local build) |
| [#43](https://github.com/DenisYumaev/ghost-bus-la/pull/43) | Publish engine: load, validate, atomic swap (ADR-007) | [ ] [038](quizzes/038-publish-engine.md) | [ ] | n/a | n/a (not deployed yet) |
| [#44](https://github.com/DenisYumaev/ghost-bus-la/pull/44) | Serving tables, `make migrate`, `make publish` | [ ] [039](quizzes/039-serving-tables.md) | [ ] | n/a | n/a (not deployed yet) |
| [#45](https://github.com/DenisYumaev/ghost-bus-la/pull/45) | Line slugs in URLs (ADR-028) | n/a (small; covered by quiz 039 Q2-style questions) | [ ] | n/a | n/a |
| [#46](https://github.com/DenisYumaev/ghost-bus-la/pull/46) | API app and `GET /v1/lines/{line}/reliability` (ADR-013) | [ ] [040](quizzes/040-api-reliability.md) | [ ] | n/a | n/a (not deployed yet) |
| [#47](https://github.com/DenisYumaev/ghost-bus-la/pull/47) | Line list, detail, stops, system summary, feed health endpoints | [ ] [041](quizzes/041-more-endpoints.md) | [ ] | n/a | n/a (not deployed yet) |
| [#48](https://github.com/DenisYumaev/ghost-bus-la/pull/48) | Trend and trip-outcomes endpoints, keyset cursor | [ ] [042](quizzes/042-trend-outcomes.md) | [ ] | n/a | n/a (not deployed yet) |
| [#49](https://github.com/DenisYumaev/ghost-bus-la/pull/49) | Method endpoint from the build's thresholds | [ ] [043](quizzes/043-method.md) | [ ] | n/a | n/a (not deployed yet) |
| [#50](https://github.com/DenisYumaev/ghost-bus-la/pull/50) | Current cancellations from the open-date build (ADR-029) | [ ] [044](quizzes/044-current-cancellations.md) | [ ] | n/a | n/a (not deployed yet) |
| [#51](https://github.com/DenisYumaev/ghost-bus-la/pull/51) | SQL drill kit (learning spec section 4) | [ ] [045](quizzes/045-sql-drills.md) | [ ] | n/a | n/a |
| [#52](https://github.com/DenisYumaev/ghost-bus-la/pull/52) | OpenAPI contract: committed document, declared errors, examples | [ ] [046](quizzes/046-openapi-contract.md) | [ ] | n/a | n/a (not deployed yet) |
| [#53](https://github.com/DenisYumaev/ghost-bus-la/pull/53) | Web scaffold: Next.js, generated API types, LA time and honest formatting, CI job | [ ] [047](quizzes/047-web-scaffold.md) | [ ] | n/a | n/a (not deployed yet) |
| [#54](https://github.com/DenisYumaev/ghost-bus-la/pull/54) | Line page: summary sentence, heatmap, cancellations | [ ] [048](quizzes/048-line-page.md) | [ ] | n/a | n/a (not deployed yet) |
| [#55](https://github.com/DenisYumaev/ghost-bus-la/pull/55) | Home, line list, method and status pages | [ ] [049](quizzes/049-web-pages.md) | [ ] | n/a | n/a (not deployed yet) |
| [#56](https://github.com/DenisYumaev/ghost-bus-la/pull/56) | M2 VM: t4g.medium, Elastic IP, inbound 80/443 | [ ] [050](quizzes/050-m2-vm.md) | [ ] | n/a | n/a |

**Suggested order, if you take them:** 004, 005, and 006 first, because they describe what is live in AWS right now. Then 002, 001, and 003.

## What I learned (drafts)

### PR #1 · ADR-021

>

### PR #2 · Scaffold

>

### PR #3 · ADR-003 and ADR-004

>

### PR #4 · State bucket

>

### PR #5 · Data bucket

>

### PR #7 · VM

>

### PR #8 · Self-test

>

### PR #9 · Fixtures

>

### PR #10 · Snapshot core

>

### PR #12 · Spool and fetch log

>

### PR #13 · S3 write and backoff

>

### PR #14 · Uploader

>

### PR #15 · Stream runner

>

### PR #16 · Service entry point

>

### PR #17 · Health and heartbeat

>

### PR #18 · Docker image

>

### PR #19 · Deploy

>
