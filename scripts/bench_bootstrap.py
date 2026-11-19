"""Benchmark the bootstrap models at a chosen scale (ADR-027).

    uv run python scripts/bench_bootstrap.py DAYS REPLICATES SCRATCH.duckdb [WAREHOUSE] [--check]

Copies the warehouse's int_trip_cells onto DAYS consecutive dates (about 1 in 50 trips flipped
to missed so rates vary), rebuilds int_windows, then runs the three bootstrap models' SQL with
the given replicate count in a file-backed scratch database (so DuckDB can spill to disk), at
2 threads and a 3 GB memory limit. Prints row counts and seconds per step. With --check, also
recomputes every interval with DuckDB's quantile_cont from the replicate table and prints the key
count and the largest difference (quantile_cont can't spill, so use a modest DAYS). Peak memory:
run under `/usr/bin/time -l`. Reads the warehouse read-only; writes only SCRATCH.
"""

import re
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "pipeline/dbt/models/intermediate"


def model_sql(name: str, replicates: int) -> str:
    sql = (MODELS / f"{name}.sql").read_text()
    sql = re.sub(r"\{\{ config\(.*?\) \}\}", "", sql)
    sql = re.sub(r"\{\{ ref\('(\w+)'\) \}\}", r"\1", sql)
    # The draw macro (pipeline/dbt/macros/bootstrap_draw.sql), rendered by hand.
    sql = re.sub(
        r"\{\{ bootstrap_draw\('([^']*)', '([^']*)', '([^']*)', '([^']*)', '([^']*)'\) \}\}",
        r"(hash(hash({{ var('bootstrap_seed') }}, \1, \2, \3, \4)) % \5)",
        sql,
    )
    sql = sql.replace("{{ var('bootstrap_seed') }}", "20261115")
    return sql.replace("{{ var('bootstrap_replicates') }}", str(replicates))


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--check"]
    check = "--check" in sys.argv
    days, replicates, scratch = int(args[0]), int(args[1]), args[2]
    warehouse = args[3] if len(args) > 3 else str(ROOT / "data/ghostbus.duckdb")
    con = duckdb.connect(scratch)
    con.execute("SET memory_limit = '3GB'; SET threads = 2; SET preserve_insertion_order = false")
    con.execute(f"ATTACH '{warehouse}' AS src (READ_ONLY)")
    con.execute(f"""
        CREATE OR REPLACE TABLE int_trip_cells AS
        SELECT service_date + CAST(d.i AS INTEGER) AS service_date, schedule_version, trip_id,
               line, direction_id,
               CASE isodow(service_date + CAST(d.i AS INTEGER))
                   WHEN 6 THEN 'saturday' WHEN 7 THEN 'sunday' ELSE 'weekday' END AS day_type,
               hour_local,
               CASE WHEN hash(trip_id, d.i) % 50 = 0 THEN 'missed' ELSE outcome END AS outcome,
               announced
        FROM src.int_trip_cells, range({days}) AS d(i)""")  # noqa: S608
    con.execute("""
        CREATE OR REPLACE TABLE int_windows AS
        WITH b AS (SELECT min(service_date) AS f, max(service_date) AS l FROM int_trip_cells)
        SELECT '28d' AS time_window, l - 27 AS window_start, l AS window_end FROM b
        UNION ALL SELECT '90d', l - 89, l FROM b
        UNION ALL SELECT 'all', f, l FROM b""")
    (n,) = con.execute("SELECT count(*) FROM int_trip_cells").fetchall()[0]
    print(f"trips: {n:,} over {days} dates, {replicates} replicates")
    for name in ("int_bootstrap_weights", "int_bootstrap_replicates", "int_bootstrap_intervals"):
        start = time.time()
        con.execute(f"CREATE OR REPLACE TABLE {name} AS {model_sql(name, replicates)}")
        (rows,) = con.execute(f"SELECT count(*) FROM {name}").fetchall()[0]  # noqa: S608
        print(f"{name}: {rows:,} rows in {time.time() - start:.1f} s")
    if check:
        (n_keys, worst) = con.execute(CHECK).fetchall()[0]
        print(f"check against quantile_cont: {n_keys:,} keys, max difference {worst:.1e}")


CHECK = """
    WITH ref AS (
        SELECT grain, time_window, line, direction_id, day_type, hour_local,
               quantile_cont(n_missed / n_trips, 0.025) FILTER (WHERE n_trips > 0) AS lo,
               quantile_cont(n_missed / n_trips, 0.975) FILTER (WHERE n_trips > 0) AS hi,
               quantile_cont(n_unplanned / n_missed, 0.025) FILTER (WHERE n_missed > 0) AS slo,
               quantile_cont(n_unplanned / n_missed, 0.975) FILTER (WHERE n_missed > 0) AS shi
        FROM int_bootstrap_replicates
        GROUP BY ALL
    )
    SELECT count(*), max(greatest(
        abs(r.lo - i.missed_rate_ci_low), abs(r.hi - i.missed_rate_ci_high),
        coalesce(abs(r.slo - i.unplanned_share_ci_low), 0),
        coalesce(abs(r.shi - i.unplanned_share_ci_high), 0)))
    FROM ref AS r
    JOIN int_bootstrap_intervals AS i
        ON r.grain = i.grain AND r.time_window = i.time_window
        AND r.line IS NOT DISTINCT FROM i.line
        AND r.direction_id IS NOT DISTINCT FROM i.direction_id
        AND r.day_type IS NOT DISTINCT FROM i.day_type
        AND r.hour_local IS NOT DISTINCT FROM i.hour_local
"""


if __name__ == "__main__":
    main()
