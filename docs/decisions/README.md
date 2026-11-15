# Decision records

Every architectural and system decision in Ghost Bus LA, one file each. An ADR (architecture decision record) says what was decided, why, what was rejected, and what would change the decision.

**Rules**

- ADRs are a history, not a current-state document. A changed decision gets a new ADR that supersedes the old one; accepted ADRs are never edited (CLAUDE.md hard rule 13).
- When documents disagree, accepted ADRs win over the specs (CLAUDE.md, "Precedence").
- Claude writes every section, including "Why"; an ADR is accepted on its evidence (ADR-022).
- Smaller decisions live in the component specs (`docs/spec/`) and in each PR's "Trade-offs" section.

## Index

Update this table in the same PR that adds or changes an ADR.

| # | Decision | Status | Supersedes or superseded by |
| --- | --- | --- | --- |
| [001](001-ingestion-decisions.md) | Ingestion: raw bytes, crosswalk, UTC and service dates, ingest every line | Accepted; decisions 1 and 3 to be superseded by 021, decision 6's key format by 004 | → 021, 004 |
| [002](002-product-direction.md) | Build a rider-facing product (web, API, alerts) on the pipeline | Accepted | Supersedes the v1 spec |
| [003](003-operating-standards.md) | Operating standards: explain-back merge gate (predictions optional), SLOs and error budget, incident log, tools on evidence | Accepted; decision 1 superseded | → 022 |
| [004](004-bronze-storage-guardrails.md) | Bronze storage: content-addressed keys, conditional writes, deny-delete and no-overwrite policy, instance role, remote state | Accepted | Supersedes 001 decision 6's key format |
| [021](021-realtime-source-websocket.md) | Realtime source: WebSocket snapshots; cancellations from trip updates | Proposed (accepted after the M0 size measurement) | Supersedes 001 decisions 1 and 3 |
| [022](022-claude-writes-all-review-replaces-gates.md) | Claude writes all code and ADRs; quizzes logged, not gated; tests and independent review replace the owner gates | Accepted | Supersedes 003 decision 1, learning spec section 3, and the owner Why-rewrite rule |

## Planned

Already decided in `docs/SPEC.md` section 5, which holds the one-line why and the rejected alternative for each. Each one is written as an ADR when its work starts. The milestones are expected, not fixed.

| # | Decision | Expected |
| --- | --- | --- |
| 011 | One VM with Docker Compose | M0 |
| 015 | DuckDB and dbt on Parquet; no warehouse | M1 |
| 016 | cron first, Airflow in M4 | M1 |
| 007 | Postgres serves precomputed aggregates; atomic table swap | M2 |
| 012 | Postgres on the VM with nightly dumps to S3 | M2 |
| 013 | Sync FastAPI endpoints with a connection pool | M2 |
| 017 | Web on Vercel, API on the VM, same parent domain | M2 |
| 019 | No staging environment | M2 |
| 006 | Hot path separate from batch path | M3 |
| 008 | Transactional outbox for alerts, at-least-once plus idempotency keys | M3 |
| 009 | Passwordless email-link auth, server-side sessions | M3 |
| 010 | Verification is a POST from a page, not a GET link | M3 |
| 018 | Email through a transactional provider behind an adapter | M3 |
| 014 | In-process TTL cache plus HTTP caching; no Redis | M5 |
| 005 | Likely-missing detector: micro-batch baseline first, streaming only on evidence | M5–M6 |
| 020 | Dataset on Hugging Face and GitHub Releases, not a public bucket | M6 |

New decisions that come up during the build take the next free number after 022.

## Template

```markdown
# ADR-NNN: <decision, as a short sentence>

- **Status:** Proposed | Accepted | Superseded by ADR-NNN
- **Date:** YYYY-MM-DD
- **Supersedes:** (if any)
- **Evidence:** (probe, measurement, or incident that informs it)

## Context
## Decision
## Why
## Alternatives considered
## Consequences
## Would change if
```
