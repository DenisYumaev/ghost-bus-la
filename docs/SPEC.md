# Ghost Bus LA — Master Spec

Version 2.0 · 2026-11-11 · Owner: Denis Y · Working name; rename freely

This is the master spec. It replaces the v1 "Ghost Bus Tracker" spec, which described a data platform; ADR-002 records the change. The project is now a **rider-facing product** (web app, API, alerts) built on the data pipeline, positioned for software engineering internships at startups and mid-size companies, with data engineering as the specialty.

## 0. How to read this spec

| File | Covers |
| --- | --- |
| `docs/SPEC.md` (this file) | The outcome, product scope, architecture, decisions, milestones, risks |
| `docs/spec/01-data-pipeline.md` | Sources, ingest, bronze, decode, dbt models, missed-trip method, data quality |
| `docs/spec/02-api.md` | REST API, auth, Postgres schema, performance budgets |
| `docs/spec/03-alerts.md` | Cancellation detection, matching, outbox, delivery, likely-missing flags |
| `docs/spec/04-web.md` | Next.js app: routes, components, accessibility, performance |
| `docs/spec/05-infra-ops.md` | AWS, Terraform, CI/CD, observability, SLOs, security, backups, cost |
| `docs/spec/06-learning.md` | How the owner learns from the build; interview question bank |
| `docs/decisions/` | Decision records (ADRs). ADR-001 and ADR-002 exist; planned ones are listed in section 5 |

**Precedence when documents disagree:** accepted ADRs, then the component specs, then this file, then `CLAUDE.md` conventions. If you find a conflict, stop and raise it; don't pick silently.

**Priority tags:** **P0** must ship. **P1** should ship. **P2** is a stretch. Never start a P1 while a P0 in the same milestone is unfinished.

**`VERIFY`** marks a fact that was not confirmed when this was written. Confirm it before building on it and record the answer in an ADR or in section 10.

## 1. The outcome: the resume this project must produce

Everything in this spec exists to make the following entry true, measurable, and defensible in a 45-minute deep-dive. Requirements flow backward from these lines.

### 1.1 Positioning

> A software engineer who is unusually strong at data: shipped a product real people use, on top of a pipeline he built and has run in production for months.

### 1.2 Target resume entry (SWE version)

**Ghost Bus LA** · Creator and sole engineer · `<live URL>` · Nov 2026 – present
*Python, FastAPI, PostgreSQL, TypeScript, Next.js, DuckDB, dbt, Airflow, AWS, Terraform, Docker*

1. Built and launched a web app that warns LA Metro riders when their bus is canceled; `[riders]` riders subscribed and `[alerts_sent]` alerts delivered, p95 `[alert_p95_s]` s after a cancellation is posted
2. Designed an at-least-once alert pipeline with a transactional outbox and idempotency keys, so crashes and retries never drop or duplicate an alert; verified with property-based tests and `[drills]` fault-injection drills
3. Shipped a public REST API serving reliability data for `[lines]` bus lines at p95 `[api_p95_ms]` ms under `[rps]` requests/s, with `[coverage]`% test coverage, CI/CD, and infrastructure as code, running at $`[cost]`/month
4. Built an idempotent data pipeline that has archived `[snapshots]` realtime snapshots and classified `[trips]` scheduled trips; results match Metro's published cancellation rates within 1 point on `[recon]`% of lines
5. Found that `[missed_rate]`% of scheduled trips never ran and `[unplanned_share]`% of those were never announced; published the method and an open dataset

Use four on a one-page resume. For data engineering roles, lead with 4 and 5, then 1 and 3.

**Never fill a bracket with an estimate.** Every bracket has one definition and one source of truth (1.3). `make resume-metrics` prints the current real values (requirement in M7).

### 1.3 Metric registry

| Placeholder | Definition | Source of truth | Target |
| --- | --- | --- | --- |
| `riders` | Users with a verified email and at least one active commute | `app.users`, `app.commute` | 100 by end of launch week; 300 stretch |
| `alerts_sent` | Outbox rows with status `sent` | `app.alert_outbox` | Report actual |
| `alert_p95_s` | p95 of `sent_at − first_seen_at`, trailing 30 days | `app.alert_outbox`, `app.cancellation_event` | ≤ 120 s |
| `drills` | Chaos drills run with a written result | `docs/drills/` | ≥ 8 |
| `lines` | Metro-operated lines with classified trips | `gold.fct_trip_outcomes` | All Metro-operated lines |
| `api_p95_ms`, `rps` | From the committed k6 report | `docs/perf/` | ≤ 200 ms at 50 rps |
| `coverage` | Line coverage of `services/` and `packages/` | CI coverage report | ≥ 85% |
| `cost` | Monthly AWS bill | Cost Explorer | ≤ $35 |
| `snapshots` | Successful, non-duplicate snapshots archived | fetch log | Report actual |
| `trips` | Rows in `fct_trip_outcomes` | gold | Report actual |
| `recon` | Share of lines within 1 percentage point of Metro's monthly report | `fct_reconciliation_monthly` | ≥ 90%, every exception explained |
| `missed_rate`, `unplanned_share` | See pipeline spec, section 8 | gold | Report actual, with intervals |
| `uptime` (optional line) | External probe success, monthly | uptime monitor | ≥ 99.5% |

### 1.4 Evidence a reviewer can click

- Live app, with a status page showing real uptime and feed health
- Public GitHub repo: green CI, tests, ADRs, runbook, incident write-ups
- API docs (OpenAPI) and an open dataset with a data dictionary
- A write-up: "I measured how much LA bus service disappears without warning" (M6 draft, M8 publish)
- A 2-minute demo video (M7)

### 1.5 Interview stories this build must generate

Each is a real problem with a decision, a trade-off, and a result. The milestone that produces it is in brackets.

1. **The alert that must not duplicate or vanish.** Outbox, idempotency keys, `SKIP LOCKED` [M3]
2. **Canceled trip, feed outage, or broken GPS?** The `unknown` and `likely_untracked` outcomes [M1, M4]
3. **The trip at 25:10 and the night the clocks change.** Service dates and DST [M1]
4. **Every trip ID changed overnight.** Schedule versioning through Metro's December service change [M4]
5. **Email scanners ate the login links.** Why verification is a POST, not a GET [M3]
6. **My numbers disagreed with Metro's.** Debugging a reconciliation gap [M4, M6]
7. **Why not Kafka, RDS, or Kubernetes.** Streaming judged against a measured baseline (ADR-005); cost and simplicity decisions with stated scale-up paths [M2, M5, M6]
8. **What the first users changed.** A feature cut or added because of rider feedback [M6, M8]
9. **The leaked AWS key.** Caught, rotated in minutes, habits changed [already happened; write it down]
10. **Running a coding agent against real infrastructure.** Hard rules, plan-before-apply, and the explain-back merge gate (ADR-003) [every milestone]

## 2. Product

### 2.1 Problem

An LA Metro rider can see when the next bus is predicted to arrive. They can't easily learn that their usual 7:40 trip was canceled until they are standing at the stop, and nobody tells them how reliable their commute actually is. Metro publishes a monthly cancellation percentage per line ([Metro](https://www.metro.net/riding/nextrip)), which is too coarse and too late for a commute decision.

### 2.2 Users

| User | Job to be done | What they get |
| --- | --- | --- |
| Daily rider with a fixed commute (primary) | "Tell me before I leave if my bus isn't coming" | Commute alerts by email |
| Rider choosing how to travel | "Is this line dependable at the time I ride?" | Reliability by line, stop, hour |
| Transit advocate or reporter | "Give me numbers I can cite" | Findings, method, open dataset, API |

### 2.3 What already exists, and what is different here

- **Metro's monthly Bus Cancellation Report:** percentage of trips canceled per line, Metro-operated lines only ([Metro](https://www.metro.net/riding/nextrip)).
- **Metro's realtime feed** marks some trips `CANCELED`, hours ahead in the cases seen so far (`docs/research/day1-probe.md`). No rider-facing tool pushes that to riders. Metro's older canceled-service API, which its developer page says powered an experimental "My Canceled Bus" tool ([developer page, mirrored](https://backiee.wasmer.app/https_developer_metro_net/api)), is dead: its data stops in October 2022.
- **Transit app, Google Maps, Metro arrivals:** predicted arrivals.

This product must do three things none of those do:

1. **Push, not pull.** Alerts for *your* commute, instead of a list you have to check.
2. **Reliability history.** "This trip window misses 6% of the time at 5 p.m.", by line, stop, and hour.
3. **Unplanned misses.** Trips that never ran and were never marked canceled in the feed. The pipeline measures them; nothing public does.

### 2.4 Scope

**P0 (the product is not launched without these)**

- Look up any Metro-operated bus line: reliability by hour and day type, current announced cancellations
- Create an account by email link, save a commute (line, direction, stop, days, time window)
- Email alert when a trip in the commute window is announced as canceled
- One-click unsubscribe, account deletion, privacy page
- Public API with OpenAPI docs
- Method page in plain language, with limitations
- Status page: feed health and uptime

**P1**

- Stop-level reliability and a "your commute" reliability summary
- Findings page with three validated findings
- Open dataset with a data dictionary
- Reconciliation against Metro's monthly report, published
- Alert digesting when several trips in one window are canceled
- "Likely missing right now": a live list of trips flagged by the baseline detector, with its measured precision published (alerts spec, section 8)

**P2 (pick at most two, in M7)**

- Commute alerts from likely-missing flags, only if measured precision clears its bar (alerts spec, section 8)
- Spanish UI and alert emails
- Weekly commute reliability digest
- Equity analysis using Metro's Equity Focus Communities
- Web push notifications

### 2.5 Non-goals

Trip planning, live maps, rail, native mobile apps, SMS, payments, contracted lines in headline metrics, any agency other than LA Metro. `agency_id` is carried in every table so a second agency is possible later, but nothing is built for it.

### 2.6 Product risks and validation gates

| Risk | How it is tested | Gate |
| --- | --- | --- |
| Cancellations are posted too late to act on | From the archive: distribution of advance notice (scheduled departure minus first seen) | **M1 exit.** If the median is under 10 minutes, the reliability lookup and the likely-missing list become the hero features, and announced-cancellation alerts become secondary. Record the decision in an ADR. |
| Riders don't want this | Talk to 5 riders before building alerts, 10 more during soft launch | **M2 exit.** Write up what was heard in `docs/research/interviews.md`. Change the commute form if needed. |
| The owner isn't an LA rider | Recruit riders through LA transit communities and advocacy groups; treat outreach as engineering work with a weekly target | 20 soft-launch users by end of M6 |
| Metro's terms restrict this use | Read the Metro API and GTFS terms | **M0.** Attribute data to LA Metro; state "not affiliated with LA Metro" in the footer; don't use Metro logos. |

Candidate communities to verify and approach: LA transit subreddits and Discords, Streets For All, Move LA, ACT-LA, the Bus Riders Union, Streetsblog LA. Read each community's rules on self-promotion first, and ask for feedback instead of posting a link. One builder's post-mortem describes being banned from communities for dropping links to a finished app ([DEV Community](https://dev.to/reykankp/zero-users-one-job-offer-the-honest-post-mortem-of-my-ai-side-project-211m)).

### 2.7 Honesty rules (product copy and write-ups)

- Say "announced cancellation" for a trip marked `CANCELED` in Metro's realtime feed and "unplanned missed trip" for what the pipeline infers. Never "Metro hid" or "Metro failed to report": what the `CANCELED` flag covers isn't documented, so make no claim about why a trip wasn't marked.
- Every inferred number carries its interval and links to the method page.
- Alerts based on Metro's feed say "Metro announced". Alerts based on inference say "our estimate" and state the measured precision.
- State the limitations on the method page: untracked buses, contracted lines excluded, detours counted as partial.

## 3. System architecture

### 3.1 Overview

```text
                         ┌────────────── LA Metro ──────────────┐
                         │ realtime WebSocket: vehicle positions│
                         │ and trip updates (incl. CANCELED)    │
                         │ GTFS static schedule (GitLab ZIP)    │
                         └──────────────────┬───────────────────┘
                                            ▼
                                   ┌─────────────────┐
                                   │ ingest (stream) │  raw bytes, fetch log, heartbeat
                                   └───┬─────────┬───┘
                     local spool + S3  │         │  local spool
              ┌────────────────────────┘         └───────────────┐
              ▼                                                  ▼
   BATCH PATH (every 10 min)                          HOT PATH (seconds)
   bronze → decode → dbt silver → gold                 detector: diff cancellation
              │                                        snapshots → events
              ▼                                                  │ one transaction
   publish: atomic swap into                                     ▼
   Postgres `serving` schema                     Postgres `app`: events + alert outbox
              │                                                  │
              ▼                                                  ▼
        ┌──────────┐   reads serving + app          ┌──────────────────┐
        │ FastAPI  │◄───────────────────────────────│ alert worker     │──► email provider
        └────┬─────┘                                └──────────────────┘
             ▼
     Next.js web app (Vercel)  ·  public API users  ·  open dataset
```

**Two paths, on purpose.** Alerts need seconds; reliability statistics need correctness and can lag by 10 minutes. They share the raw data and nothing else, so a slow or broken batch run can never delay an alert, and a bug in alert parsing can never corrupt statistics.

### 3.2 Components

| Component | Responsibility | Tech | Runs on |
| --- | --- | --- | --- |
| `ingest` | Hold the realtime WebSocket connections, cut a snapshot every 30 to 60 s, store it to the local spool then S3, write the fetch log, ping the heartbeat; download GTFS static daily | Python, websockets, httpx | VM |
| `detector` | Read new cancellation snapshots from the spool, upsert events, insert outbox rows; (P1) flag trips likely missing right now | Python, Postgres | VM |
| `alert-worker` | Claim outbox rows, send email, retry, record result | Python, Postgres, email API | VM |
| `pipeline` | Compact, decode, dbt build, bootstrap intervals, publish | Python, DuckDB, dbt; cron then Airflow (M4) | VM |
| `api` | REST API for the web app and the public | FastAPI, SQLAlchemy 2, psycopg 3 | VM |
| `postgres` | `app`, `serving`, `ops` schemas | PostgreSQL 16 | VM |
| `caddy` | TLS, reverse proxy, compression | Caddy | VM |
| `web` | Rider-facing app | Next.js, TypeScript, Tailwind | Vercel |
| Storage | Bronze archive, backups | S3 | AWS |

### 3.3 What an alert goes through, end to end

1. `ingest` cuts a trip-updates snapshot from the WebSocket (60 s cadence), writes it to the spool atomically, logs it, uploads to S3.
2. `detector` sees the new file, parses it, and diffs it against open events.
3. For each new cancellation it opens one transaction: upsert the event, find matching commutes, insert outbox rows with a unique dedupe key, commit.
4. `alert-worker` claims pending rows with `FOR UPDATE SKIP LOCKED`, sends the email with an idempotency key, marks the row `sent`.
5. The API shows the alert in the user's history; metrics record `sent_at − first_seen_at`.

Failure at any step leaves the system retryable: a crash before commit loses nothing because the snapshot is replayed; a crash after sending but before marking `sent` is absorbed by the idempotency key.

### 3.4 Budgets on one VM (t4g.medium, 4 GB)

Estimates; measure in M2 and M5 and record the real numbers.

| Process | Memory |
| --- | --- |
| Postgres | 400 MB |
| API (2 workers) | 300 MB |
| ingest, detector, alert-worker | 250 MB |
| Caddy, metrics agent | 200 MB |
| Airflow (LocalExecutor), from M4 | 1.3 GB |
| DuckDB/dbt runs (peak, `memory_limit` set) | 1 GB |
| Headroom | ~500 MB, plus 2 GB swap |

Start on t4g.small through M1 (ingest only), resize to t4g.medium in M2.

## 4. Repository layout

```text
ghost-bus-la/
├── CLAUDE.md                 # rules for Claude Code (read first)
├── README.md                 # question → finding → how it works → run it → limitations
├── Makefile                  # up, test, lint, backfill, resume-metrics, ...
├── compose.yml               # local stack
├── compose.prod.yml          # production overrides
├── pyproject.toml            # uv workspace root
├── packages/
│   └── ghostbus_core/        # shared: config, GTFS time and service-date math, models, logging
├── services/
│   ├── ingest/               # WebSocket snapshotter, spool, uploader, fetch log
│   ├── detector/             # cancellation diffing, matching, outbox writes
│   ├── alerts/               # delivery worker, email templates, provider adapters
│   ├── api/                  # FastAPI app, routers, schemas, Alembic migrations
│   └── publish/              # gold → Postgres serving loader
├── pipeline/
│   ├── compact/  decode/     # Python steps before dbt
│   ├── dbt/                  # models: silver/, intermediate/, gold/; tests; seeds
│   └── dags/                 # Airflow DAGs (M4)
├── analysis/                 # bootstrap intervals, backtests, findings notebooks, metrics
├── web/                      # Next.js app
├── infra/                    # Terraform: main configuration, and bootstrap/ for the state bucket
├── deploy/                   # deploy.sh, Caddyfile, cloud-init
├── tests/                    # cross-service tests, fixtures/ (recorded real snapshots)
├── scripts/                  # resume_metrics.py, one-off tools
└── docs/
    ├── SPEC.md  spec/  decisions/  runbook.md
    ├── incidents/  drills/  perf/  research/
    └── learning/             # predictions, quiz log, daily log
```

Each service has its own `pyproject.toml`, `Dockerfile`, and `tests/`. Shared logic lives in `ghostbus_core` and nowhere else.

## 5. Decision register

ADR-001 and ADR-002 are written and accepted. Rows 003 onward are decisions already made in this spec; Claude Code writes each as an ADR when the related work starts, and the owner rewrites the "why" paragraph in his own words (learning spec).

| # | Decision | Why | Rejected, and why | Scale-up path |
| --- | --- | --- | --- | --- |
| 001 | Ingestion: Metro API first, raw bytes, 30/60 s cadence, crosswalk, UTC | Accepted; decisions 1 and 3 superseded by 021; see file | See file | |
| 002 | Product direction: a rider-facing app with an API and alerts, on top of the pipeline | Accepted; see file | See file | |
| 003 | Operating standards: explain-back merge gate, SLOs with an error budget, incident log, new tools adopted only on evidence | "It runs" is a claim; a met SLO is evidence. Understanding, not typing, is the bottleneck when an agent writes the code | No gate: fast, but the code stops being the owner's. A 99.9% capture target: unrealistic on one VM | |
| 004 | Bronze storage and guardrails: content-addressed keys written with `If-None-Match`, a rebuildable `derived/` prefix, deletes on `bronze/*` denied by bucket policy, an instance role, Terraform state in S3. Supersedes the key format in ADR-001 decision 6 | Deduplication is atomic in S3, with no lookup and no race; "bronze is sacred" is enforced by AWS, not by a README | Fetch time in the key with list-before-write: a race. Moving raw files to cold storage: per-object fees exceed the saving | |
| 005 | Likely-missing detector: a 1-minute micro-batch baseline first; a streaming version only if the baseline misses its latency or precision bars | A tool should beat a measured baseline before it is adopted | Redpanda and a stateful consumer from the start: cost and operations with no proven need | Redpanda with event-time timers and replay |
| 006 | Hot path separate from batch path | Alerts need seconds; stats need correctness | One pipeline for both: couples alert latency to batch runtime | |
| 007 | Postgres serves precomputed aggregates; pipeline swaps tables atomically | Fast, simple reads; the API never sees a half-loaded table | API queries DuckDB/Parquet directly: slower, concurrency limits | Read replica, or a warehouse (Snowflake/BigQuery) with the same dbt models |
| 008 | Transactional outbox for alerts, at-least-once plus idempotency keys | Correct under crashes without a message broker | Send email inline in the detector: lost or duplicated on crash. Kafka/SQS: extra infrastructure for one consumer | SQS between detector and workers |
| 009 | Passwordless email-link auth, server-side sessions | No passwords to store or leak; the product already depends on email | Passwords: liability. OAuth-only: excludes riders without Google accounts. JWT sessions: can't revoke | Add OAuth as a second method |
| 010 | Verification is a POST from a page, not a GET link | Email security scanners follow GET links and would burn single-use tokens | Plain GET verification | |
| 011 | One VM with Docker Compose | About $33/month; one person can operate and explain all of it | ECS/EKS: cost and complexity with no benefit at this load. Serverless: poor fit for a process that holds a connection open 24/7 | ECS services behind a load balancer |
| 012 | Postgres on the VM with nightly dumps to S3 | RDS roughly doubles the bill | RDS | RDS with point-in-time recovery |
| 013 | Sync FastAPI endpoints with a connection pool | Simpler to debug; the load test proves it meets the budget | Async everywhere | Async endpoints for hot routes |
| 014 | In-process TTL cache plus HTTP caching; no Redis | Data changes at most every 10 minutes; one API instance | Redis: another service to run for no measurable gain | Redis when there is more than one API instance |
| 015 | DuckDB + dbt on Parquet; no warehouse | Free, fast at this size, portable SQL | Snowflake/BigQuery: cost | Point dbt at a warehouse |
| 016 | cron first, Airflow in M4 | Feel the need (retries, backfills) before adopting the tool | Airflow from day one; Dagster (fewer postings name it) | |
| 017 | Web on Vercel, API on the VM, same parent domain | Free hosting and previews for the frontend; same-site cookies | Everything on the VM | |
| 018 | Email through a transactional provider behind an adapter | Deliverability is a product feature | Running a mail server | Second provider as failover |
| 019 | No staging environment; preview deploys for web, feature flags and a compose-based smoke test for backend | Cost; one engineer | Full staging stack | Staging VM |
| 020 | Dataset published on Hugging Face and GitHub Releases, not a public S3 bucket | No egress bill surprises; discoverable | Public S3 bucket | |
| 021 | Realtime source: snapshots cut from the Metro API WebSocket; announced cancellations read from trip updates. Supersedes ADR-001 decisions 1 and 3 | The probe found the REST realtime endpoints empty and the canceled-service API dead since 2022; the WebSocket is live and needs no key | Waiting for a Swiftly key before archiving: loses days of history | Swiftly GTFS-realtime as a second source |

## 6. Milestones

Day 1 is Thursday, November 12, 2026. Project time is about 36 hours a week (6 hours a day, 6 days); the rest of the day is interview prep (learning spec). Each milestone ends with a tagged release, a short demo to yourself recorded on video, and the quiz in the learning spec.

**Finals week:** mark your exam dates now and move M4's P1 items into M5 if they collide. The ingest and alert services keep running regardless.

### M0 · Nov 12–13 · The archive is alive (P0)

The realtime stream shows only the present. Every day without the archive is history that can't be recovered.

- Read `docs/research/day1-probe.md` (the probe is done) and write ADR-021 from it
- Request a Swiftly API key as a second realtime source
- Read Metro's API and GTFS terms of use
- New repo, scaffolded to the layout in section 4: uv workspace, ruff, mypy, pytest, pre-commit, CI skeleton, README stub
- Write ADR-003 and ADR-004 from the decision register
- Terraform: a state bucket (bootstrap) and the S3 backend; the data bucket with versioning, `prevent_destroy`, and a deny-delete policy on `bronze/*`; the budget; an instance role; a t4g.small VM reachable only through SSM. `plan` reviewed by the owner before `apply`
- Deal with the AWS resources the scrapped repo created (a data bucket and a budget): import them into the new Terraform or destroy them. Don't leave them unmanaged
- Verify conditional writes on a scratch `selftest/` prefix
- `ingest` running in production: both WebSocket streams and the GTFS ZIP, spool-then-S3, fetch log, external heartbeat
- Measure a full day of snapshot sizes, raw and compressed, and set the cadences from them

**Accept when:** 24 hours of snapshots exist with at least 99% of scheduled polls attempted; killing the container for an hour shows up as a gap in the fetch log and the heartbeat alert fires.
**Resume claim unlocked:** "run continuously since November 2026."
**Chaos drill:** kill `ingest`; block S3 access for 10 minutes and confirm the spool drains afterwards.

### M1 · Nov 14–20 · Schedule and first truth (P0)

- GTFS static loader with versioning from day one; daily download and hash check
- Compaction and decode steps; DuckDB over Parquet
- dbt silver models; schedule expansion; trip matching v1 on trip ID
- `fct_trip_outcomes` v1: `ran`, `missed`, `unknown`; `fct_feed_health`
- Measure advance notice of announced cancellations (product gate, 2.6)
- Start rider conversations (5)

**Accept when:** for any past service date, one query answers "how many trips did line 754 schedule, and how many ran?"; the reconciliation identity holds (scheduled = sum of outcomes); the advance-notice ADR is written.
**Resume claim unlocked:** bullet 4, first numbers.
**Owner-written:** service-date math, schedule expansion SQL, trip matching v1, outcome classification v1 (learning spec).
**Chaos drill:** run the same day twice; outputs must be identical.

### M2 · Nov 21–27 · Public read-only product (P0)

- Postgres with `serving` and `ops` schemas; `publish` with atomic swap
- API: lines, line reliability, current cancellations, system summary, feed health, health checks
- Next.js: home, line list, line page, method page, status page
- Domain, TLS, deploy pipeline (GitHub Actions → VM), Vercel for web
- Resize to t4g.medium

**Accept when:** the public URL shows real reliability numbers for every Metro-operated line, refreshed within 15 minutes; a merge to `main` deploys with a health check and automatic rollback.
**Resume claim unlocked:** "live at `<URL>`"; start applying with the link.
**Owner-written:** one endpoint end to end (`GET /v1/lines/{line}/reliability`).
**Chaos drill:** deploy a build that fails its health check; confirm rollback.

### M3 · Nov 28–Dec 4 · Alerts (P0)

- Email-link auth, sessions, account deletion
- Commute create, read, update, delete
- `detector`: snapshot diffing, events, matching, outbox
- `alert-worker`: delivery, retries, dead-letter state, unsubscribe
- Alert history in the app; dogfood with 5 people

**Accept when:** a replayed day of real cancellation snapshots produces exactly one alert per (commute, trip) no matter how many times it is replayed or where the process is killed; p95 detection-to-send is under 120 s in production.
**Resume claims unlocked:** bullets 1 and 2.
**Owner-written:** the commute-matching query.
**Chaos drill:** kill the worker mid-send; kill the detector mid-transaction; replay a snapshot 10 times.

### M4 · Dec 5–11 · Trust (P0 and P1)

- Airflow replaces cron; one-command backfill
- Full schedule versioning. The current schedule's `feed_end_date` is Dec 12, so the service change is expected on Dec 13: prepare in M4, watch it live at the start of M5
- Block inference (`likely_untracked`), `partial`, trip-update cancellations, fuzzy-match fallback
- Schema-drift detection; alert routing with runbook entries
- First reconciliation against Metro's monthly report

**Accept when:** a full-history backfill completes from bronze with no network calls and reproduces published numbers; match rate stays above 95% across the service change; every line differing from Metro's report by more than 2 points has a written explanation.
**Resume claims unlocked:** `[recon]`; story 4.
**Owner-written:** the full decision table in `fct_trip_outcomes`.
**Chaos drills:** load a day twice; drop a feed for 6 hours; swap in a new schedule mid-week.

### M5 · Dec 12–18 · Production quality (P0 and P1)

- Metrics, dashboards, SLOs, alert rules; structured logs
- Load test with k6; fix the top two bottlenecks; caching and ETags
- Security review (checklist in infra spec); dependency and secret scanning in CI
- Accessibility pass (WCAG 2.2 AA); Lighthouse budgets in CI
- Stop-level reliability; commute summary; backup restore drill
- Baseline likely-missing detector and the live list (P1)

**Accept when:** the committed k6 report meets the API budget; a restore from last night's backup succeeds on a scratch database; Lighthouse performance and accessibility are at least 90 on the line page.
**Resume claims unlocked:** bullet 3 numbers; `[uptime]`.
**Chaos drill:** restore the database from backup; fill the disk to 90% on a scratch volume.

### M6 · Dec 19–25 · Evidence and soft launch (P1)

- Cluster-bootstrap intervals; threshold sensitivity; hand validation of 50 trips
- Findings page; open dataset v1 with data dictionary; README and architecture diagram
- Score the likely-missing detector over at least 7 service days; write the go/no-go on alerts from flags and on streaming (ADR-005)
- Soft launch to 20 riders; 10 feedback conversations; write-up draft

**Accept when:** three findings each have a method note, an interval, and a hand-check record; 20 real riders have active commutes.
**Resume claims unlocked:** bullet 5; story 8.
**Owner-written:** the cluster bootstrap.

### M7 · Dec 26–Jan 1 · Polish and rehearsal (P1 and P2)

- Fix the top five feedback items; at most two P2 features
- Rebuild the whole stack from Terraform on a scratch account or region in under 30 minutes
- `make resume-metrics`; demo video; three mock deep-dives with the question bank

**Accept when:** every bracket in section 1.2 prints a real value; the owner answers all 30 bank questions without notes.

### M8 · Jan 2–8 · Launch (P0)

Launch in the first full week of January, when commuters are back and startups open internship roles.

- Public launch in LA transit communities; outreach to advocates and local press; Show HN; publish the write-up
- Applications and direct emails to engineers and founders with the live link
- Week-one numbers: signups, alerts sent, unsubscribes, feedback themes

**Accept when:** `[riders]` is at or above 100, or the write-up explains honestly why not and what was learned.

## 7. Scope control

**Cut order when time runs short:** P2 features, equity analysis, fuzzy matching, stop-level reliability, the likely-missing list, findings page polish, Airflow (stay on cron with a manual backfill script), open dataset. **Never cut:** the poller, alert correctness tests, CI, the method page, the reconciliation check.

**Change policy:** a new feature idea goes into `docs/ideas.md`, not into the current milestone. Scope changes need a new ADR.

## 8. Engineering standards

Definition of done for the project:

- [ ] `make up` runs the full stack locally from a fresh clone in under 10 minutes
- [ ] `make test` runs offline, with no API keys, in under 5 minutes
- [ ] CI on every PR: lint, type check, unit and integration tests, dbt build on fixtures, web tests, Terraform validate
- [ ] All AWS resources in Terraform; nothing created in the console
- [ ] No secrets in the repo; secret scanning in CI
- [ ] Every alert rule links to a runbook entry
- [ ] Every incident has a blameless write-up in `docs/incidents/` (ADR-003)
- [ ] Every number on the site, in the README, and on the resume traces to a query in the repo
- [ ] README answers in order: what question, what was found, how it works, how to run it, limitations

Definition of done for a PR is in `CLAUDE.md`.

## 9. Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Cancellation history lost while `ingest` is down | Medium | Spool-then-upload, external heartbeat, every gap logged |
| Metro's beta API changes shape | Medium | Raw bytes always stored; schema fingerprints; detector fails closed and pages the owner |
| The realtime WebSocket is the only keyless source, and its limits are undocumented | Medium | One connection per stream, reconnect with backoff; a Swiftly key requested in M0 as a second source |
| Cancellations announced too late to be useful | Medium | M1 gate; reliability lookup and the likely-missing list as the fallback heroes |
| Too few riders | High | Outreach is scheduled work from M1; soft launch before public launch; advocates as distribution |
| Scope: four systems, one person | High | P0/P1/P2 tags, cut order, milestones with acceptance tests |
| Learning lags behind the code Claude writes | High | Merge gate: the owner must pass the quiz for every PR (learning spec) |
| Email lands in spam | Medium | Authenticated domain (SPF, DKIM, DMARC), plain emails, low volume, easy unsubscribe |
| Storing rider emails and commute patterns | Medium | Minimal data, deletion endpoint, no third-party trackers, encrypted backups |
| Untracked buses inflate missed counts | High | Block inference, hand validation, stated limitation |
| AWS bill surprise | Low | Budget alerts at 50/80/100% of $40; no NAT gateways; one instance |

## 10. Open questions

Settled by the probe on Nov 11 (`docs/research/day1-probe.md`):

| Question | Answer | Consequence |
| --- | --- | --- |
| Do the Metro API realtime endpoints return fresh data? | REST: no, empty lists. WebSocket: yes, vehicle timestamps a median 22 s old | Ingest is a WebSocket snapshotter |
| Protobuf or JSON? | JSON, one message per vehicle or trip | One decode adapter |
| Is the canceled-service API usable? | No. Last updated 2022-10-04; detail endpoints return 500 | Not a source |
| Are cancellations announced elsewhere? | Yes: trip updates marked `CANCELED`, some more than 2 hours ahead | The detector reads trip updates |
| Do realtime trip IDs match GTFS? | Yes, 64 of 64 sampled | Exact matching; the fuzzy fallback is a safety net only |
| Does realtime carry `startDate`? | Yes | Service date comes from the feed |
| Do canceled entries disappear after the trip's time? | No, they linger for hours | Close events by time, not by absence |
| When is the next service change? | Expected Dec 13 (`feed_end_date` is Dec 12) | Live test at the start of M5 |
| Is there service-alert text? | No | The LLM alert-cause idea is dropped |

Still open:

| Question | Why it matters | Settle by |
| --- | --- | --- |
| How far in advance do cancellations first appear, as a distribution? | Product gate 2.6 | M1, from a week of archive |
| What does the `CANCELED` flag cover? Contracted lines? Unplanned cancellations? | Product copy and reconciliation scope | M1 to M4, by comparing with outcomes and Metro's report |
| Does the WebSocket throttle or drop long-lived connections? | Ingest design | M0, first 48 hours |
| Snapshot sizes, raw and compressed | Cadence and storage cost | M0 |
| What does Metro's monthly report count, and are past months available? | Reconciliation | M4 |
| Metro's terms for the API and for publishing derived data | Dataset release | M0 |
| Is "My Canceled Bus" still live anywhere? | Differentiation | M1 |
| Email provider free-tier limits and idempotency-key support | Alert delivery | M3 |

## 11. Sources

[Metro API](https://api.metro.net) · [Metro API guide](https://lacmta.github.io/metro-api-v2/docs/intro) · [Metro developer page, mirrored](https://backiee.wasmer.app/https_developer_metro_net/api) · [Metro arrivals and cancellation report](https://www.metro.net/riding/nextrip) · [LA Metro bus GTFS](https://gitlab.com/LACMTA/gtfs_bus) · [Metro GTFS notes](https://lacmta.github.io/gtfs-bus) · [Mobility Database](https://mobilitydatabase.org/feeds/gtfs/mdb-29) · [Transitland archive](https://transit.land/feeds/f-9q5-metro~losangeles) · [Metro board report, Feb 2026](https://datamade-metro-pdf-merger.s3.amazonaws.com/2026-0066.pdf) · [TransitCenter on ghost buses](https://transitcenter.org/ghost-buses-are-haunting-riders-across-america/)
