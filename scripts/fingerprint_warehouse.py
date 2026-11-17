"""Fingerprint every table and view in the local dbt warehouse, independent of row order.

    uv run python scripts/fingerprint_warehouse.py [data/ghostbus.duckdb] > before.json

Used by the M1 chaos drill (run the same day twice; outputs must be identical): fingerprint,
re-run compact and decode for a day, re-sync, rebuild, fingerprint again, and diff. Read-only.
"""

import json
import sys

import duckdb

# One md5 per row (the row cast to text), sorted, then md5 of the whole list: row order and
# physical layout don't matter, any changed value or row count does.
FINGERPRINT = """
    SELECT count(*), coalesce(md5(string_agg(h, '' ORDER BY h)), 'empty')
    FROM (SELECT md5(CAST(t AS VARCHAR)) AS h FROM {table} AS t)
"""


def fingerprints(con: duckdb.DuckDBPyConnection) -> dict[str, list[object]]:
    tables = con.execute(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') ORDER BY 1, 2"
    ).fetchall()
    out: dict[str, list[object]] = {}
    for schema, name in tables:
        ident = f'"{schema}"."{name}"'
        n, digest = con.execute(FINGERPRINT.format(table=ident)).fetchall()[0]
        out[f"{schema}.{name}"] = [n, digest]
    return out


def main() -> None:
    db = sys.argv[1] if len(sys.argv) > 1 else "data/ghostbus.duckdb"
    with duckdb.connect(db, read_only=True) as con:
        print(json.dumps(fingerprints(con), indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
