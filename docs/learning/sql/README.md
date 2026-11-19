# SQL drills

These drills cover the SQL block of the learning plan (`docs/spec/06-learning.md` section 4): 18 problems written against tables shaped like this project's warehouse, each checked automatically against a reference answer. Like everything else in ADR-022, they're optional practice.

## The loop

```bash
make sql-drill          # list the problems and which ones you've passed
make sql-drill P=01     # copy the starter to attempts/ and start the clock
#   write your query under "-- your query below" in docs/learning/sql/attempts/01-*.sql
make sql-check P=01     # run it; PASS or NOT YET, with a few rows that differ
make sql-shell          # duckdb shell on the practice tables (.tables, DESCRIBE trips, try things)
```

On your first pass, the time and the number of checks are appended to `docs/learning/sql-log.md`, and the checker points you to the reference solution. Read it even when you passed: every solution has a comment explaining the trap and the main alternative. Restarting a problem with `make sql-drill P=NN` gives a clean timed run: the clock resets and your previous attempt is saved as a `.bak` file next to it. `make sql-shell` needs the DuckDB command-line tool (`brew install duckdb`); the Python package doesn't include it.

## The progression

| Tier | Problems | Plan weeks | Skills |
| --- | --- | --- | --- |
| 1 | 01–06 | 1–2 | joins, anti-joins, GROUP BY / HAVING, conditional aggregation, CTEs, GTFS time math |
| 2 | 07–13 | 3–4 | ROW_NUMBER dedup, latest row per group, running totals, DENSE_RANK, LAG, gaps and islands |
| 3 | 14–18 | 5–8 | timed mediums: combine the above under the target time in each header |

Each header gives the exact output columns, whether row order is checked, and one "Watch for" line naming the trap. Write it from memory first. The goal from learning spec section 1 is a medium problem in 20 minutes.

## How the checking works

- The practice data (`practice_data.sql`) is synthetic and deterministic: it's rebuilt in memory on every check, so you can't break it, and the answers never change. **None of its numbers describe Metro.** Only the line numbers are real.
- Your result and the reference result are compared as multisets of rows. Column names don't matter; column order, row count, and duplicates do. Row order counts only when the header says `Order: checked`.
- Floats match within 0.001, so a rounding difference in the last place still passes. NULL never matches 0.
- The SQL is DuckDB, written in a portable style. Where Postgres differs (integer division, `make_interval`, `QUALIFY`), the solution comments say so, because interviews usually use Postgres.

## The tables

`make sql-shell`, then `.tables` and `DESCRIBE <table>`, or `uv run python scripts/sql_drill.py schema` for each table with sample rows.

| Table | Grain | Mirrors |
| --- | --- | --- |
| `lines` | one row per line | `dim_line` |
| `stops`, `line_stops` | stop; line × stop | `dim_stops`, `dim_line_stop` |
| `trips` | one scheduled trip (one week, 2026-11-02 to 11-08) | `int_schedule_expanded` |
| `trip_outcomes` | one classified trip | `fct_trip_outcomes` |
| `cancellations` | one posting of a cancellation alert | `stg_cancellations` |
| `vehicle_positions` | one ping (line 754, 2026-11-03) | `stg_vehicle_positions` |
| `fetch_log` | one fetch per feed per minute (2026-11-03) | `stg_fetch_log` |

## Beyond the 18

For free practice on real data, open the warehouse read-only: `duckdb -readonly data/ghostbus.duckdb` (after `make dbt`). Try rewriting a problem against the real tables, or reading the project's own models (`pipeline/dbt/models/`) and predicting their output before you run them.
