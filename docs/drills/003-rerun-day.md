# Drill 3: run the same day twice; outputs must be identical

- **Date:** 2026-11-17, 18:13–19:29 UTC
- **Milestone:** M1 (`docs/SPEC.md` M1 chaos drill; hard rule 2, everything is idempotent)
- **Code:** `main` at `3a59947` (outcomes v1 merged); DuckDB 2.0.0
- **Day:** service date 2026-11-15, the only one with outcomes so far (the first schedule ZIP arrived that day). Its dbt input is UTC days 2026-11-14 to 16 (`make dbt-sync` copies the day before and after, ADR-023), so all three were re-derived.

## What was done

1. Built the warehouse (`make dbt`) and fingerprinted every table and view with `scripts/fingerprint_warehouse.py`. Per table it records:
   - the row count;
   - an md5 over the sorted md5s of every row, so row order doesn't matter but any changed value does;
   - an md5 over the column names and types.

   The session time zone is pinned to UTC.
2. **Same input, built again:** ran `make dbt` a second time and fingerprinted again.
3. **Same days, derived again from bronze:** ran `make compact` and `make decode` for UTC days 15, then 14 and 16. Each run writes new parts and a `_SUCCESS` marker, then deletes the older run. Then ran `make dbt-sync START=2026-11-15 END=2026-11-15` and `make dbt`, and fingerprinted again.

Bronze was only read. Compacted and decoded data is derived and can be rebuilt from it at any time.

## What was expected

All fingerprints identical: the same raw messages give the same compacted parts, the same decoded rows, and the same silver and gold tables.

## What happened

| Check | Result |
| --- | --- |
| dbt build, twice on the same input (18:16) | `PASS=138 WARN=1 ERROR=0`. The warning is the known `vehicle_reports_name_one_trip`, 8 rows. **All 31 tables and views identical** |
| Re-compaction, UTC day 15 (18:18–18:21) | trip updates: 1,440 snapshots in 8 parts; 0 missing objects, 0 bad log lines, no fetch-log hours missing |
| Re-decode, UTC day 15 (to 18:29:53) | vehicle positions: 2,881 snapshots → 2,924,942 rows; trip updates: 1,440 snapshots → 39,195,711 rows; 0 quarantined |
| Re-compaction, UTC days 14 and 16 (18:42–19:15) | day 14: 2,880 and 1,436 snapshots; day 16: 2,880 and 1,438 snapshots. 0 missing objects, 0 bad log lines, no fetch-log hours missing |
| Re-decode, UTC days 14 and 16 (to 19:24:14) | day 14: 3,331,689 position rows and 42,417,214 trip-update rows; day 16: 3,647,677 and 45,281,878. 0 quarantined |
| New markers | All 12 `_SUCCESS` markers for UTC days 14–16 (2 stages × 2 feeds × 3 days) are dated 18:19–19:24 UTC today. The previous compacted markers for day 15 were from 05:28–05:29 UTC |
| Rebuild over the re-derived days (dbt done 19:28:31) | `PASS=138 WARN=1 ERROR=0`. **All 31 tables and views identical** to the baseline: 290,086,638 rows in total, including `fct_trip_outcomes` (9,534) and `fct_feed_health` (1,728) |

**Passed.** For service date 2026-11-15, every step from bronze to gold gives the same output when run again.

## Limits

- One service date and one decoder version (3). A decoder change is expected to change the output; `sync` refuses data from an older decoder version (ADR-023).
- Ingest wasn't re-run: bronze is the fixed input by design (hard rule 1).
- The fingerprint compares each row as DuckDB prints it. DuckDB prints floats in the shortest form that reads back exactly, so two different values can't print the same. The print format can change between DuckDB versions, so both fingerprints must come from the same version, as they did here.
- The first comparison (dbt twice, and the UTC day 15 re-derivation, 18:35) used an earlier version of the script without the column-type hash or the UTC pin. The final comparison used the hardened script for both baseline and rebuild: the baseline was taken over the same local files before the re-sync.

## What was fixed

Nothing in the pipeline. Review of the drill hardened the fingerprint script:
- the column-type hash and the UTC time zone;
- a row alias that can't clash with a column name;
- escaping for quotes in table names;
- only the open database is read.

Each change has a test. The script stays in the repo for the next drill, or for any refactor that shouldn't change results.
