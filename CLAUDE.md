# CLAUDE.md — Ghost Bus LA

Instructions for Claude Code in this repo. Keep this file short; details live in `docs/`.

## What this is

A rider-facing product for LA Metro bus riders: reliability lookup by line and stop, and email alerts when a trip in a saved commute is canceled. It is built on a pipeline that archives Metro's realtime feeds and classifies every scheduled trip. One owner, one VM, about $33 a month.

It is also a portfolio project with two goals, in this order:

1. **Make the resume entry in `docs/SPEC.md` section 1 true and measurable.** Every feature traces to a line there.
2. **Teach the owner.** He must be able to explain and defend every file. `docs/spec/06-learning.md` makes that concrete; its merge gate is binding.

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

Follow the loop in `docs/spec/06-learning.md` section 2 on every PR: **brief → owner predicts → plan → build (tests first) → walkthrough → quiz → owner breaks something → log.**

- Predictions are optional and paused at the owner's request since 2026-11-12 (ADR-003). When they resume, ask for the prediction before showing your plan.
- Explain each non-trivial choice in one or two sentences, with the main alternative you rejected. Define a new term the first time it appears.
- **Do not write the seven owner-written pieces** (learning spec, section 3). Write their tests and fixtures, leave the implementation as a marked TODO, then review his work like a staff engineer.
- Keep PRs small enough to explain in 15 minutes (about 400 changed lines, generated files aside).
- After the walkthrough, record five quiz questions in `docs/learning/quizzes/` and add the PR to `docs/learning/owed.md`. A PR may merge with its quiz owed; a milestone isn't done until every owed quiz scores 4 of 5 (ADR-003). Don't accept vague answers.
- When reviewing his code, point out problems and let him fix them. Don't rewrite silently.
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
```

Add `make dbt`, `make backfill START= END=`, and `make resume-metrics` as those pieces arrive.

## Definition of done for a PR

- [ ] Linked to a milestone item in `docs/SPEC.md` section 6
- [ ] Tests written first; they fail without the change and pass with it
- [ ] Lint, types, and all CI jobs green
- [ ] Idempotency and failure behavior covered by a test where relevant
- [ ] Docs updated: spec if behavior changed, runbook if an alert was added, ADR if a decision was made
- [ ] No new `VERIFY` left unrecorded
- [ ] Walkthrough given; quiz recorded and listed in `docs/learning/owed.md` (passing it and "What I learned" are due by the end of the milestone, ADR-003)
- [ ] PR description: what, why, how tested, spec section, trade-offs

## Commit and branch conventions

Branches `<type>/<short-topic>` (`feat/…`, `fix/…`, `docs/…`, `infra/…`, `chore/…`). One logical change per commit. Never commit to `main` directly.

## Current state

Update this section at the end of every session.

- **As of Nov 11, 2026:** this is a new repo. It holds the specs, ADR-001, ADR-002, and the probe report. No code yet. **Nothing is archiving.**
- AWS: account on the paid plan; IAM user `denis-dev` with MFA; CLI configured for `us-west-2`.
- An earlier, scrapped repo (`la-ghost-bus`) created a data bucket and a budget with Terraform. Its code and decision records are not part of this project. M0 imports or destroys those two resources.
- The data-source probe is done: `docs/research/day1-probe.md`. Realtime comes from the Metro API WebSocket; cancellations come from trip updates; the canceled-service API and the REST realtime endpoints are dead. ADR-001 decisions 1 and 3 are superseded by this (ADR-021, to be written in M0).
- Next: M0 in `docs/SPEC.md` section 6.
