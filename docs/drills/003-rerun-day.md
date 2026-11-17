# Drill 3: run the same day twice; outputs must be identical

- **Date:** 2026-11-17, 18:13–18:35 UTC
- **Milestone:** M1 (`docs/SPEC.md` M1 chaos drill; hard rule 2, everything is idempotent)
- **Code:** `main` at `3a59947` (outcomes v1 merged)
- **Day:** UTC day 2026-11-15 (the only service date with outcomes so far: the first schedule ZIP arrived that day)

## What was done

1. Built the warehouse (`make dbt`) over the synced range (service date 2026-11-15; UTC days 14–16) and fingerprinted every table and view with `scripts/fingerprint_warehouse.py`: per table, the row count and an md5 over the sorted md5s of every row, so row order doesn't matter but any changed value does.
2. **Same input, built again:** `make dbt` a second time, then fingerprinted again.
3. **Same day, derived again from bronze:** `make compact DAY=2026-11-15` and `make decode DAY=2026-11-15`. Each writes a new run and its `_SUCCESS` marker, then deletes the older run. Then `make dbt-sync START=2026-11-15 END=2026-11-15`, `make dbt`, and a third fingerprint.

Bronze was only read. Compacted and decoded data is derived and can be rebuilt from it at any time.

## What was expected

All three fingerprints identical: the same raw messages give the same compacted parts, the same decoded rows, and the same silver and gold tables.

## What happened

| Check | Result |
| --- | --- |
| dbt build, twice on the same input | 138 passed, 1 known warning (8 ambiguous vehicle reports), 0 errors, both times. **All 31 tables and views identical** |
| Re-compaction | trip updates: 1,440 snapshots in 8 parts, 0 missing objects, 0 bad log lines, no fetch-log hours missing. New compacted markers for both feeds, written 18:19–18:20 UTC (the previous ones were from 2026-11-17 05:28–05:29 UTC) |
| Re-decode | vehicle positions: 2,881 snapshots → 2,924,942 rows; trip updates: 1,440 snapshots → 39,195,711 rows; 0 quarantined. New decoded markers 18:23 and 18:29 UTC |
| Rebuild after re-deriving the day | Same dbt result. **All 31 tables and views identical** to the first build: 290,086,638 rows in total, including `fct_trip_outcomes` (9,534) and `fct_feed_health` (1,728) |
| Wall-clock | compact and decode about 11 min 20 s (18:18:33–18:29:53); sync and dbt about 4 min |

**Passed.** The pipeline from bronze to gold is deterministic for this day.

## Limits

- One day only, and one decoder version (3). A decoder change is expected to change the output; `sync` refuses data from an older decoder version (ADR-023).
- Ingest wasn't re-run: bronze is the fixed input by design (hard rule 1).
- The fingerprint casts each row to text, so it compares values as DuckDB prints them. Two floats that differ beyond the printed precision would compare equal. No model rounds before output, and the counts matched too.

## Follow-ups

None needed. `scripts/fingerprint_warehouse.py` stays in the repo for the next drill or for any refactor of a model that shouldn't change the results.
