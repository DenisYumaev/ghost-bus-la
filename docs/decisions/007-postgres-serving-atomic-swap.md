# ADR-007: Postgres serves precomputed aggregates; publish swaps tables atomically

- **Status:** Accepted
- **Date:** 2026-11-17
- **Supersedes:** nothing. Writes up the planned decision in `docs/SPEC.md` section 5 (row 007), and settles a point the specs leave open: who defines the `serving` tables
- **Evidence:**
  - Drill 3 (`docs/drills/003-rerun-day.md`): one service date's warehouse is 290 million rows across 31 tables and takes about 4 minutes to build. That is batch work, not something to run per API request.
  - `fct_trip_outcomes` has one row per scheduled trip, about 9,500 a day (`docs/research/observations.md`). The aggregates the API serves are far smaller.

## Context

The API needs reliability numbers by line, direction, day type and hour, plus a few other read models (API spec section 7). They are computed by dbt in DuckDB from Parquet. The API runs on the same small VM as ingest and the pipeline. API spec section 6 says Alembic manages the `app` schema. Pipeline spec section 13 says `publish` loads `serving.<table>__new` and renames it into place. Neither says who owns the `serving` and `ops` table definitions.

## Decision

1. **The API reads only Postgres.** It never opens DuckDB or Parquet. Every number it serves is precomputed by the pipeline and copied into the `serving` schema.
2. **`publish` swaps whole tables.** For each serving table it:
   - loads `serving.<table>__new`, then validates it (row count, null keys; pipeline spec section 13);
   - in one transaction, renames the live table to `__old`, renames `__new` to the live name, and drops `__old`;
   - records the load in `ops.publish_run`.
3. **`publish` owns the `serving` table definitions.** Each serving table's DDL, including its indexes, lives with `publish` and is applied to `__new` on every load. A column change ships with the code that fills it.
4. **Alembic owns everything durable.**
   - It creates the `serving` and `ops` schemas, the `ops` tables, and (from M3) the `app` schema.
   - Migrations follow expand, deploy, contract, so each release works with the previous release's schema (API spec section 6).
5. **Roles:**
   - one database role for the migrations, which owns everything;
   - an `api` role that can read `serving` and `ops` (and, from M3, read and write `app`);
   - a `pipeline` role that can create tables in `serving` and write `ops.publish_run` and `ops.feed_status`.

   The role grants come with the deploy work (M2), not the first migration.

## Why

Precomputing keeps every API request a single indexed lookup over a small table, which is how the 200 ms p95 budget is met (API spec section 8). DuckDB is the right engine for the batch build, but it isn't built for many concurrent readers on one VM while another process rebuilds the files they read. The swap gives readers either the whole old table or the whole new one, never a half-loaded mix.

Letting `publish` own the serving DDL follows from the swap. Every load creates the table fresh, so an Alembic migration on the live table would be overwritten by the next publish, and two places would define the same columns. Durable state is different: `ops` and `app` rows must survive deploys and are written by several services, so their schema needs ordered, reviewed migrations.

## Alternatives considered

- **The API queries DuckDB or Parquet directly** (SPEC section 5): no copy step, but slow cold reads and limited concurrency, and the file it reads could be mid-rebuild.
- **Alembic also owns the serving tables, and `publish` truncates and inserts:** one schema tool, but readers would see an empty or half-filled table during the load unless it ran in one long transaction. That transaction would hold locks and bloat the table on every publish.
- **Materialized views refreshed concurrently:** atomic for readers, but needs the source data inside Postgres, which means copying the raw outcomes too.

## Consequences

- Schema changes to a serving table are code changes in `publish`, tested by its integration tests. No migration is needed.
- `data_as_of` comes from `ops.publish_run`, the time of the last successful load of each table (API spec section 1).
- The `serving` schema is rebuildable from the pipeline, so backups exclude it (infra spec section 10).
- A swap takes a short exclusive lock on the table names. Readers queue for that moment, not for the load.

## Would change if

- Serving data outgrows one Postgres on the VM, or the load test misses the budget: a read replica, or a warehouse running the same dbt models (SPEC section 5).
- Serving tables need cross-table consistency, such as a line list that must match the reliability grid exactly. Then all tables would swap in one transaction, or move to a versioned schema (`serving_v<n>`) behind a pointer.
