# CLAUDE.md — Ghost Bus LA

Instructions for Claude Code in this repo. Keep this file short; details live in `docs/`.

## What this is

A rider-facing product for LA Metro bus riders: reliability lookup by line and stop, and email alerts when a trip in a saved commute is canceled. It is built on a pipeline that archives Metro's realtime feeds and classifies every scheduled trip. One owner, one VM, about $33 a month.

It is also a portfolio project with two goals, in this order:

1. **Make the resume entry in `docs/SPEC.md` section 1 true and measurable.** Every feature traces to a line there.
2. **Teach the owner.** He must be able to defend the design in an interview. Since ADR-022 there is no quiz gate; `docs/learning/interview-decisions.md` is the record of trade-offs he must be able to explain. The owner wants to finish as fast as possible.

## Read before working

| When | Read |
| --- | --- |
| Start of every session | This file; `docs/SPEC.md` sections 6 (milestones) and 10 (open questions); every file in `docs/decisions/`; `docs/research/day1-probe.md` |
| Touching ingest or dbt | `docs/spec/01-data-pipeline.md` |
| Touching the API or database | `docs/spec/02-api.md` |
| Touching detector or alerts | `docs/spec/03-alerts.md` |
| Touching `web/` | `docs/spec/04-web.md` |
| Touching infra, CI, deploy, monitoring | `docs/spec/05-infra-ops.md` |

Precedence: accepted ADRs, then component specs, then `docs/SPEC.md`, then this file. If two documents disagree, stop and ask. If the spec is wrong or silent, propose an ADR; don't improvise quietly.

## How to work with the owner

Every PR, per ADR-022: **brief → plan → build (tests first) → independent review → written walkthrough in the PR description → record the quiz.** The owner wants it finished fast and at high quality: cut ceremony, never tests or review.

- Predictions, checkpoints, and drills are optional practice (ADR-022). Don't ask for them.
- Explain each non-trivial choice in one or two sentences, with the main alternative you rejected. Define a new term the first time it appears.
- **Claude writes everything**, including the seven core pieces in learning spec section 3 and every ADR's "Why". Those pieces need property-based tests (Hypothesis) for pure logic, hand-checked fixtures for SQL covering the edge cases the specs name, and dbt grain tests.
- **Before each merge, run an independent review:** the `reviewer` agent on every PR, plus `sql-reviewer` on SQL and dbt changes. Give it the diff and the spec, not your reasoning. Fix the findings or answer them in the PR description.
- Keep PRs small enough to explain in 15 minutes (about 400 changed lines, generated files aside).
- After the walkthrough, record five quiz questions in `docs/learning/quizzes/` and add the PR to `docs/learning/owed.md`. Don't ask the owner to take them; they gate nothing (ADR-022). If he does answer one, grade it strictly.
- In every PR that makes or changes a decision worth defending, add or update its entry in `docs/learning/interview-decisions.md`.
- The owner is new to SQL and to most of this stack, and strong in Python and statistics. Pitch explanations accordingly.

## Hard rules

1. **Bronze is sacred.** Never write code that modifies or deletes anything under `bronze/`. Raw messages are stored exactly as received (ADR-001 decision 2), and the bucket policy denies deletes on `bronze/*`.
2. **Everything is idempotent.** Any job, migration, snapshot, or alert may run twice. Bronze keys are content hashes written with `If-None-Match: *`; silver and gold overwrite whole service-date partitions. Prove idempotency with a test.
3. **The archive comes first.** `ingest` depends only on network, disk, and S3. It never imports app code or needs Postgres. No change may cost it more than one snapshot interval of downtime.
4. **Alerts never duplicate and never vanish.** Outbox rows are written in the same transaction as the event. Never send email inside a database transaction. Never bypass `dedupe_key`.
5. **Times:** store UTC. Service dates follow the GTFS rule in `America/Los_Angeles`; times can pass 24:00 (ADR-001 decision 5). Rider-facing matching uses local calendar day and time at the rider's stop.
6. **Never join sources on `trip_id` directly.** Use the crosswalk and the schedule version in force (ADR-001 decision 4).
7. **No SQL in routers.** Repositories own queries. All queries are parameterized.
8. **Terraform:** show `terraform plan` and wait for explicit approval before `apply` or `destroy`. No NAT gateways, one instance, nothing above `t4g.medium`. Never weaken the bucket's `prevent_destroy`, versioning, or deny-delete policy. `terraform init` uses `-backend-config=backend.hcl`.
9. **Credentials:** use the configured AWS profile. Never create IAM users or access keys, never run `aws configure`, never print or log credentials, never commit `*.tfstate`, `backend.hcl`, `.env`, or keys.
10. **Tests run offline** against fixtures in `tests/fixtures/`. No test calls Metro, AWS, or an email provider.
11. **Honest numbers.** No invented metrics anywhere: README, site copy, commit messages, resume lines. Every number traces to a query or a committed report.
12. **Product copy** follows `docs/SPEC.md` section 2.7: "announced cancellation" versus "unplanned missed trip"; never imply Metro hides data; always "not affiliated with LA Metro".
13. **Changing an accepted ADR means writing a new ADR** that supersedes it. Don't edit accepted ADRs.
14. **Don't add scope.** New ideas go to `docs/ideas.md`. P0 before P1 before P2.
15. **`VERIFY` items** in the specs must be checked before building on them. Record the answer.

## Stack

Python 3.12 · uv · ruff · mypy · pytest · Hypothesis · httpx · websockets · FastAPI · Pydantic v2 · SQLAlchemy 2 · psycopg 3 · Alembic · PostgreSQL 16 · DuckDB · dbt-duckdb · Airflow (from M4) · Next.js · TypeScript (strict) · Tailwind · Vitest · Playwright · Docker Compose · Caddy · Terraform · GitHub Actions · AWS (S3, EC2, SSM, IAM).

Don't add a dependency, service, or tool outside this list without an ADR: new tools are adopted on evidence of a measured problem. Not in this plan: Redpanda or Kafka, code against Swiftly (a key is requested only as a fallback), Iceberg, Redis, Kubernetes, RDS, a staging stack, the Evidence or Streamlit dashboard.

## Layout

Target layout is in `docs/SPEC.md` section 4: `packages/ghostbus_core/`, `services/{ingest,detector,alerts,api,publish}/`, `pipeline/{compact,decode,dbt,dags}/`, `analysis/`, `web/`, `infra/` (with `bootstrap/`), `deploy/`, `tests/`, `scripts/`, `docs/`.

## Commands

```bash
make install   # locked dev dependencies
make up        # local stack
make test      # all offline tests; keep under 5 minutes
make lint      # ruff, mypy, fixture size check (add eslint and tsc when web/ exists)
make fmt
make plan      # terraform plan; there is deliberately no apply target
make gtfs-versions  # rebuild dim_schedule_version in derived/ from the GTFS ZIPs in bronze
make gtfs-load      # that, plus extract each new version's tables to derived/decoded/gtfs/<version>/
make compact DAY=2026-11-14  # one closed UTC day of snapshots into derived/compacted/
```

Add `make dbt`, `make backfill START= END=`, and `make resume-metrics` as those pieces arrive.

## Definition of done for a PR

- [ ] Linked to a milestone item in `docs/SPEC.md` section 6
- [ ] Tests written first; they fail without the change and pass with it
- [ ] Lint, types, and all CI jobs green
- [ ] Idempotency and failure behavior covered by a test where relevant
- [ ] Docs updated: spec if behavior changed, runbook if an alert was added, ADR if a decision was made
- [ ] No new `VERIFY` left unrecorded
- [ ] Independent review run (`reviewer`, plus `sql-reviewer` for SQL); findings fixed or answered
- [ ] Written walkthrough in the PR description; quiz recorded and listed in `docs/learning/owed.md` (optional for the owner, ADR-022)
- [ ] `docs/learning/interview-decisions.md` updated if a decision was made or changed
- [ ] PR description: what, why, how tested, spec section, trade-offs

## Commit and branch conventions

Branches `<type>/<short-topic>` (`feat/…`, `fix/…`, `docs/…`, `infra/…`, `chore/…`). One logical change per commit. Never commit to `main` directly.

## Current state

Update this section at the end of every session.

- **As of Nov 17, 2026 (M0 acceptance met; M1 in progress). The archive is live:** ingest has run on the VM since 2026-11-13 05:54 UTC (image `7da9646` since 2026-11-15), with both feeds and hourly fetch logs in S3 every day since (checked 2026-11-15). Earlier notes saying it wasn't deployed were stale. Heartbeat on since 2026-11-15 (Healthchecks.io, URL in SSM `/ghost-bus-la/heartbeat-url`), and the SNS email subscription is re-created and confirmed.
- **Merged (PRs #1–#26):** ADR-003, ADR-004, ADR-021 and ADR-022 all accepted; repo scaffold with CI; conditional-write self-test (`make selftest-s3`); WebSocket fixtures; the whole ingest service: snapshot core, spool and fetch log, S3 write with backoff, uploader, stream runner, entry point, `/healthz` and heartbeat, Docker image built in CI and published to GHCR, laptop deploy tool with health-gated rollback, runbook entries, the GTFS schedule download (PR #21, deployed as `7da9646`; first ZIP stored 2026-11-15), the strict deploy SHA check (#22), the measured-day report (#23), the drill 2 record (#24), and M1's service-date math (#25) and schedule-version rule (#26).
- **Live in AWS (Terraform, owner-approved applies):** state bucket `ghost-bus-la-tfstate-<acct>` (bootstrap, local state in `infra/bootstrap/terraform.tfstate`); data bucket `la-ghost-bus-bronze-<acct>` and budget `la-ghost-bus-monthly`, imported from the scrapped repo, with the ADR-004 policy and 50/80/100% alerts; VM `i-047b5f055d9425e38` (t4g.small, SSM only, no inbound), role `ghost-bus-la-app`, status-check alarms to SNS `ghost-bus-la-ops-alerts`. Main config state is in S3; `infra/backend.hcl` and `infra/terraform.tfvars` are local and gitignored.
- **Learning (ADR-022, 2026-11-15):** no quiz gate. Quizzes 001–022 are recorded and optional. Interview prep lives in `docs/learning/interview-decisions.md`. Claude writes all code, including the former owner-written pieces, and every ADR's Why. Independent review replaces the owner as second reader.
- **Measured:** every entity reappears within 6.74 s (`docs/research/ws-cycle-timing.md`). Nov 14: 100% of scheduled cuts attempted; 0.49 GB a day gzipped across both feeds (`docs/research/measured-day-2026-11-14.md`, `scripts/measure_day.py`). M0's first acceptance criterion is met.
- **Drills 1 and 2 passed** (`docs/drills/`): drill 2 on 2026-11-16 (S3 blocked, spool drained); drill 1 on 2026-11-17 (ingest stopped gracefully for an hour: DOWN email in about 4 min, gap in the fetch log, UP on restart; a hard kill wasn't exercised). **Both M0 acceptance criteria are met.** Still owed from the M0 list: the Swiftly key request and reading Metro's terms (owner).
- **M1 in progress:** service-date math (PR #25) and the schedule-version rule (PR #26) merged. Next: the GTFS loader (extract each version's tables to `derived/decoded/gtfs/<version>/`), then compaction and decode, then dbt.
- **Workflow notes:** merge with merge commits, not squash. Retarget stacked PRs to `main` before merging their parent with `--delete-branch` (deleting a base branch closes child PRs).
