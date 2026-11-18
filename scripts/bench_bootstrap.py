"""Benchmark the bootstrap models at a chosen scale (ADR-027).

    uv run python scripts/bench_bootstrap.py DAYS REPLICATES SCRATCH.duckdb [data/ghostbus.duckdb]

Copies the warehouse's int_trip_cells onto DAYS consecutive dates (about 1 in 50 trips flipped
to missed so rates vary), rebuilds int_windows, then runs the three bootstrap models' SQL with
the given replicate count in a file-backed scratch database (so DuckDB can spill to disk), at
2 threads and a 3 GB memory limit. Prints row counts and seconds per step. Reads the warehouse
read-only; writes only SCRATCH.
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
    sql = re.sub(r"\{\{ ref\('(\w+)'\) \}\}", r"\1", sql)
    sql = sql.replace("{{ var('bootstrap_seed') }}", "20261115")
    return sql.replace("{{ var('bootstrap_replicates') }}", str(replicates))


def main() -> None:
    days, replicates, scratch = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    warehouse = sys.argv[4] if len(sys.argv) > 4 else str(ROOT / "data/ghostbus.duckdb")
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


if __name__ == "__main__":
    main()
