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
