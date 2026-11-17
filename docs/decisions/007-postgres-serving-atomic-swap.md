# ADR-007: Postgres serves precomputed aggregates; publish swaps tables atomically

- **Status:** Accepted
- **Date:** 2026-11-17
- **Supersedes:** nothing. Writes up the planned decision in `docs/SPEC.md` section 5 (row 007), and settles a point the specs leave open: who defines the `serving` tables
- **Evidence:**
  - Drill 3 (`docs/drills/003-rerun-day.md`): building one service date reads three UTC days of decoded data, about 137 million rows (2.9 + 39.2 + 3.3 + 42.4 + 3.6 + 45.3 million). Sync plus the dbt build took about 4 minutes. That is batch work, not something to run per API request.
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
   - `ops.alert_feedback` (P1) arrives with its feature.
5. **Roles** come with the deploy work (M2), not the first migration.

   | Role | Owns | Can |
   | --- | --- | --- |
   | migrations | the schemas, the `ops` and `app` tables | everything |
   | `pipeline` | every `serving` table (it creates them, so it owns them, and only the owner can rename or drop them in the swap) | create tables in `serving`; insert into `ops.publish_run`; write `ops.feed_status` |
   | `detector` | nothing | write `ops.consumer_cursor` and `ops.feed_status`; from M3, write the event and outbox tables in `app` |
   | `api` | nothing | read `serving` and `ops`; from M3, read and write `app` |

   Serving tables are new objects on every load, so plain grants would vanish at each swap. The role setup includes `ALTER DEFAULT PRIVILEGES FOR ROLE pipeline IN SCHEMA serving GRANT SELECT ON TABLES TO api`.

## Why

Precomputing keeps every API request a single indexed lookup over a small table, which is how the 200 ms p95 budget is met (API spec section 8). DuckDB is the right engine for the batch build, but it isn't built for many concurrent readers on one VM while another process rebuilds the files they read. The swap gives readers either the whole old table or the whole new one, never a half-loaded mix. They wait only for the moment of the rename, not for the load.

Keeping the serving DDL in `publish`, rather than in Alembic, keeps a serving table's definition next to the query that fills it. Serving tables hold no history: each load rebuilds them completely from gold. So there is nothing for a migration to preserve, and an ordered migration chain adds nothing. Durable state is different: `ops` and `app` rows must survive deploys and are written by several services, so their schema needs ordered, reviewed migrations.

## Alternatives considered

- **The API queries DuckDB or Parquet directly** (SPEC section 5): no copy step, but slow cold reads and limited concurrency, and the file it reads could be mid-rebuild.
- **Alembic defines the serving tables, and `publish` builds `__new` with `CREATE TABLE … (LIKE serving.x INCLUDING ALL)`:** the same atomic swap with one schema tool. Rejected because every column change would then need a migration and a `publish` change, deployed in lockstep: the migration has to land before the publish that fills the column, and the old publish must still work against the new definition. That is expand-and-contract ceremony for a table that is rebuilt from scratch anyway.
- **Alembic defines the serving tables, and `publish` truncates and inserts in one transaction:** simple, but `TRUNCATE` takes an exclusive lock, so every API read of that table waits for the whole load, seconds to minutes. Using `DELETE` instead avoids the lock but leaves dead rows to vacuum after every publish.
- **Materialized views refreshed concurrently:** atomic for readers, but needs the source data inside Postgres, which means copying the raw outcomes too.

## Consequences

- Schema changes to a serving table are code changes in `publish`, tested by its integration tests. No migration is needed.
- `data_as_of` comes from `ops.publish_run`, the time of the last successful load of each table (API spec section 1).
- The `serving` schema is rebuildable from the pipeline, so backups exclude it (infra spec section 10).
- A swap takes a short exclusive lock on the table names. Readers queue for that moment, not for the load.

## Would change if

- Serving data outgrows one Postgres on the VM, or the load test misses the budget: a read replica, or a warehouse running the same dbt models (SPEC section 5).
- Serving tables need cross-table consistency, such as a line list that must match the reliability grid exactly. Then all tables would swap in one transaction, or move to a versioned schema (`serving_v<n>`) behind a pointer.
- Serving tables start holding state that a load doesn't rebuild. Then they become durable and move to Alembic.
