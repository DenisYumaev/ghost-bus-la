# 05 · Infrastructure and operations

One VM, one database, one bucket, all defined in code. The aim is a system one person can run, explain, and rebuild from nothing in 30 minutes, for about $33 a month.

## 1. Environments

| Environment | What | Notes |
| --- | --- | --- |
| Local | `make up`: Postgres, API, detector, worker, pipeline, web, with seeded fixtures and the file email adapter | No AWS access needed |
| Preview | Vercel preview deploy per PR for the web app, pointed at production's read-only public API | Account flows are tested locally |
| Production | The VM and Vercel | `main` deploys automatically |

There is no staging stack (ADR-019). Risky backend changes ship behind a feature flag (environment variable) and are verified with the smoke test before the flag is turned on.

## 2. AWS resources (Terraform, `infra/`)

Region `us-west-2`. Terraform state lives in an S3 bucket with native lock files, created by `infra/bootstrap`; backend settings come from a gitignored `infra/backend.hcl`, so the account ID isn't committed (ADR-004).

| Resource | Details |
| --- | --- |
| S3 data bucket | Versioning on, public access blocked, SSE-S3, `prevent_destroy`. The bucket policy denies deletes on `bronze/*` for every principal. No lifecycle transitions on `bronze/`. `derived/` holds rebuildable data (ADR-004) |
| S3 `backups` bucket | Versioning on, public access blocked, 14-day expiry on database dumps |
| EC2 instance | `t4g.small` through M1, then `t4g.medium`; Ubuntu LTS arm64; 30 GB gp3; termination protection; cloud-init installs Docker |
| Elastic IP | For the API's DNS record |
| Security group | No inbound rules through M1. From M2, inbound 80 and 443 for the API. Never port 22: shell access is through SSM Session Manager |
| IAM instance role | Put and get on `bronze/*` and `derived/*`, list the bucket, write to the backups bucket, read specific SSM parameters, SSM core. No delete on bronze |
| IAM role for GitHub Actions | Assumed through OIDC; may run one SSM document on this instance. No long-lived AWS keys in GitHub |
| SSM Parameter Store | Secure strings for secrets; values are set by hand, never in Terraform files or state where avoidable |
| AWS Budget | $40 a month, email at 50%, 80%, 100% |
| CloudWatch alarm | Instance status check failed → automatic recovery and an email |

Tag every resource `project = ghost-bus-la`.

**Guardrails for Terraform work (also in `CLAUDE.md`):** show `terraform plan` and wait for the owner's approval before `apply` or `destroy`; no NAT gateways; one instance; nothing larger than `t4g.medium`; never touch the bronze bucket's protection settings.

The `denis-dev` IAM user currently has administrator access for setup. Before launch, replace it with a role limited to this project's resources, and record that in an ADR.

## 3. The VM

Docker Compose (`compose.prod.yml`). Images are built in CI and pulled from GitHub Container Registry; nothing is built on the VM.

| Service | Ports | Volumes | Restart |
| --- | --- | --- | --- |
| `caddy` | 80, 443 public | certificates | always |
| `api` | internal 8000 | none | always |
| `ingest` | none | `spool` | always |
| `detector` | none | `spool` (read-only) | always |
| `alert-worker` | none | none | always |
| `pipeline` (cron, then Airflow in M4) | Airflow UI bound to localhost only | `duckdb-tmp` | always |
| `postgres` | internal 5432 | `pgdata` | always |
| metrics agent | none | none | always |

Each container has a health check, a memory limit, and log rotation. Postgres is never exposed outside the Docker network. A 2 GB swap file is configured by cloud-init.

DNS: `<domain>` and `www` point at Vercel; `api.<domain>` points at the Elastic IP. Same parent domain, so session cookies are same-site (ADR-017).

## 4. Secrets

| Secret | Where |
| --- | --- |
| Database password, session and unsubscribe signing keys, email provider API key, heartbeat URL | SSM Parameter Store → environment at container start |
| Vercel and registry tokens | GitHub Actions secrets |

Rules: no secret in the repo, in Terraform files, in logs, or in a chat. `gitleaks` runs in pre-commit and CI. Rotate anything that is ever exposed, immediately, and write an incident note.

## 5. CI (GitHub Actions)

On every pull request, in parallel:

| Job | Runs |
| --- | --- |
| `python` | `ruff check`, `ruff format --check`, `mypy` (strict on `ghostbus_core`, `api`, `detector`, `alerts`), `pytest` with coverage (fail under 85% on those packages) |
| `integration` | Compose test stack with Postgres; API, detector, and worker integration tests; migration tests |
| `dbt` | `dbt build` against fixture Parquet, including dbt tests and unit tests |
| `web` | ESLint, `tsc --noEmit`, Vitest, build; Playwright against the local stack; Lighthouse CI on the preview |
| `contract` | Regenerate OpenAPI and the TypeScript client; fail on an uncommitted diff |
| `infra` | `terraform fmt -check`, `validate`, `tflint`; `plan` posted as a PR comment |
| `security` | `gitleaks`, `pip-audit`, `npm audit` (high and critical), Trivy on images |

All tests run offline against recorded fixtures. Target: under 10 minutes.

Branch protection on `main`: PRs only, all checks green.

## 6. CD

On merge to `main`:

1. Build and push images tagged with the git SHA.
2. GitHub Actions assumes the deploy role through OIDC and runs `deploy.sh <sha>` on the VM through SSM.
3. `deploy.sh`: record the current SHA; pull images; run Alembic migrations; `docker compose up -d` one service at a time, `ingest` last; wait for `/readyz`; run the smoke test (public endpoints return 200 with fresh `data_as_of`; a canary cancellation in a test schema produces one alert through the file adapter).
4. On any failure: redeploy the recorded SHA, mark the deploy failed, notify.
5. Write a row to `ops.deploy`.

`ingest` restarts in a few seconds and is deployed only when its image changed, so the archive gap from a deploy stays under one snapshot interval. Web deploys through Vercel on the same merge.

**Migrations** must work with both the old and new code (expand → deploy → contract in a later release). Destructive migrations need an ADR.

## 7. Observability

**Logs.** JSON lines to stdout: timestamp, level, service, event, request ID, and duration where relevant. No emails or tokens; log user IDs only. Docker rotates logs; ship them to the metrics provider's log store if its free tier allows (`VERIFY`).

**Metrics.** Each service exposes Prometheus metrics; an agent on the VM forwards them to a hosted Grafana (`VERIFY` free-tier limits; fallback: a nightly job that computes SLOs from Postgres and the fetch log, which is needed for `make resume-metrics` anyway).

| Service | Key metrics |
| --- | --- |
| `ingest` | Fetch attempts and failures by feed; fetch latency; seconds since last success by feed; spool file count and disk usage |
| `detector`, `alert-worker` | See alerts spec, section 9 |
| `pipeline` | Run duration and status by job; rows by outcome; match rate; data age |
| `api` | Request count and latency histogram by route and status; cache hit rate; database pool in use |
| Host | CPU, memory, disk, swap |

**Dashboards.** One overview (the four SLOs), one per service.

**External checks.** A heartbeat monitor for `ingest`; an uptime monitor on `https://api.<domain>/readyz` and the home page.

## 8. SLOs

Recorded in ADR-003.

| SLO | Target | Measured from |
| --- | --- | --- |
| Capture | 99.5% of minutes per feed, per calendar month: a fetch was attempted and its outcome recorded | Fetch log |
| Trip match rate | ≥ 95% per day, per source | `int_trip_crosswalk` |
| Data freshness | Serving data under 15 minutes old, 99% of the time | `ops.publish_run` |
| Alert latency | p95 detect-to-send ≤ 120 s over 30 days | Outbox |
| API availability | ≥ 99.5% per month | External monitor |
| API latency | p95 ≤ 200 ms at the origin | Request histogram |

SLOs cover only what this system controls. An error from Metro that was attempted and logged counts as captured; a minute with no attempt doesn't. Metro's own freshness and error rate are shown next to the SLOs as source health.

**Error budget:** 0.5% of a 30-day month is 216 minutes. If a month's capture budget is spent, feature work stops until the cause is fixed and an incident write-up exists. The status page shows these numbers publicly.

## 9. Alert rules and runbook

Every rule notifies by email and a Discord webhook and links to its entry in `docs/runbook.md`. Each runbook entry has: what it means, how to confirm, how to fix, how to verify the fix.

| Alert | Condition | First response |
| --- | --- | --- |
| `ingest_heartbeat_missed` | No heartbeat for 3 minutes | Check the VM and the `ingest` container; the spool protects data only while the process runs |
| `feed_stale` | A feed has no success for 5 minutes | Check Metro's status; confirm backoff; no action if upstream is down |
| `spool_disk_high` | Disk above 70% | Check the uploader and S3 permissions |
| `detector_blocked` | Detector can't parse or schema not approved | Inspect the snapshot; approve the schema or fix the parser; replay |
| `detector_lag_high` | Lag over 5 minutes | Check Postgres and the detector logs |
| `outbox_stuck` | Rows `pending` or `failed` older than 15 minutes | Check the worker and the email provider |
| `alert_dead_letter` | Any row becomes `dead` | Read `last_error`; fix; requeue if still timely |
| `pipeline_run_failed` | A job fails twice in a row | Read the job log; backfill after the fix |
| `match_rate_low` | Under 95% for a day | Check for a new schedule version |
| `reconciliation_broken` | Outcome counts don't sum to scheduled | Stop publishing; investigate |
| `data_stale` | Serving data older than 30 minutes | Check the pipeline and publish |
| `api_5xx_high` | 5xx over 1% for 5 minutes | Check the API logs and database pool |
| `api_latency_high` | p95 over 500 ms for 10 minutes | Check slow queries and cache hit rate |
| `cert_expiring` | TLS certificate under 14 days | Check Caddy renewal |
| `backup_missing` | No database dump in 26 hours | Run the backup by hand; fix the job |
| `budget_threshold` | AWS budget at 80% | Find the cost in Cost Explorer |

## 10. Backups and recovery

- **Database:** nightly `pg_dump` (custom format), encrypted, to the backups bucket; 14 days kept. The `serving` schema is excluded because it is rebuildable.
- **Bronze:** S3 versioning, and the bucket policy denies deletes.
- **Restore drill (M5):** restore last night's dump into a scratch database, run the API tests against it, record the time taken.
- **Rebuild drill (M7):** from an empty AWS region or account: `terraform apply`, deploy, restore the database, backfill serving from bronze. Target: under 30 minutes, excluding DNS.

| Loss | Recovery | Data lost |
| --- | --- | --- |
| VM | Rebuild drill | Snapshots during the outage; up to 24 hours of account changes |
| Database only | Restore the dump | Up to 24 hours of account changes |
| Serving tables | Re-run publish | None |
| Silver and gold | Backfill from bronze | None |

## 11. Security checklist (review in M5)

- [ ] HTTPS only; HSTS; security headers on API and web (`Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`)
- [ ] Session cookie attributes as specified; tokens and session IDs stored hashed
- [ ] Origin check and JSON content type on state-changing routes
- [ ] Rate limits on auth and write endpoints
- [ ] No user enumeration through auth or error messages
- [ ] Authorization check on every commute and alert route, with tests for cross-user access
- [ ] All SQL parameterized; no string-built queries
- [ ] Email content built from templates with escaped values
- [ ] Dependencies and images scanned in CI; base images pinned
- [ ] Least-privilege IAM; no port 22; root account unused, MFA on
- [ ] Backups encrypted; restore tested
- [ ] Unsubscribe links signed, scoped, and unable to do anything except pause alerts

Write a one-page threat model in `docs/security.md`: assets (emails, commute patterns, the archive), entry points, and the top five threats with their mitigations.

## 12. Privacy

- Store the minimum: email, commutes, alert history. No names, no phone numbers, no location history, no IP addresses beyond short-lived rate-limit records.
- Account deletion removes everything tied to the user within the request.
- No third-party trackers; no sale or sharing of data.
- The privacy page says this in plain words and names the email provider as the only processor that sees addresses.

## 13. Cost (estimates; record actuals monthly)

| Item | Monthly |
| --- | --- |
| EC2 `t4g.medium` | about $24.50 |
| Public IPv4 address | about $3.65 |
| EBS 30 GB gp3 | about $2.40 |
| S3 storage and requests | $1 to $2 |
| Domain | about $1 (billed yearly) |
| Vercel, email, monitoring free tiers | $0 (`VERIFY` limits) |
| **Total** | **about $33** |

New-account credits cover the first months. The account is on the paid plan, so the budget alerts are the safety net.

## 14. Incidents

Anything that loses data, sends a wrong or duplicate alert, or takes the site down for more than 5 minutes gets a blameless write-up in `docs/incidents/YYYY-MM-DD-slug.md`, using the template there (ADR-003). So does any SLO breach, any unexplained gap in bronze, and any manual action on production data. The leaked access key on November 10 is the first one to write.

## 15. Chaos drills (`docs/drills/`)

Each drill gets a short record: what was done, what was expected, what happened, what was fixed.

| # | Drill | Milestone |
| --- | --- | --- |
| 1 | Kill `ingest` for an hour | M0 |
| 2 | Block S3 for 10 minutes; confirm the spool drains | M0 |
| 3 | Run the same service date twice; compare outputs | M1 |
| 4 | Deploy a build that fails its health check | M2 |
| 5 | Kill the alert worker mid-send | M3 |
| 6 | Kill the detector mid-transaction; replay a snapshot 10 times | M3 |
| 7 | Feed outage for 6 hours; confirm trips become `unknown`, not `missed` | M4 |
| 8 | Swap in a new schedule version mid-week | M4 |
| 9 | Restore the database from backup | M5 |
| 10 | Fill a scratch disk to 90% | M5 |
| 11 | Rebuild everything from Terraform | M7 |
