"""Fingerprint every table and view in the local dbt warehouse, independent of row order.

    uv run python scripts/fingerprint_warehouse.py [data/ghostbus.duckdb] > before.json

Used by the M1 chaos drill (run the same day twice; outputs must be identical): fingerprint,
re-run compact and decode, re-sync, rebuild, fingerprint again, and diff. Read-only.

Run it from the repo root: the dbt views read the Parquet and JSON files under `data/` at the
moment they are fingerprinted, so a "before" fingerprint must be taken before a re-sync.
Compare fingerprints made with the same DuckDB version.
"""

import json
import sys

import duckdb

# Per table: row count; md5 over the sorted md5s of every row (the row cast to text), so row
# order and layout don't matter but any changed value does; and md5 over the column names
# and types, so a type change counts even when the printed values match.
ROWS = """
    SELECT count(*), coalesce(md5(string_agg(h, '' ORDER BY h)), 'empty')
    FROM (SELECT md5(CAST(__fp_row AS VARCHAR)) AS h FROM {table} AS __fp_row)
"""
COLUMNS = """
    SELECT md5(string_agg(column_name || ':' || data_type, ',' ORDER BY ordinal_position))
    FROM information_schema.columns
    WHERE table_catalog = current_database() AND table_schema = ? AND table_name = ?
"""


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def fingerprints(con: duckdb.DuckDBPyConnection) -> dict[str, list[object]]:
    con.execute("SET TimeZone = 'UTC'")  # timestamptz prints the same on every machine
    tables = con.execute(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_catalog = current_database() "
        "AND table_schema NOT IN ('information_schema', 'pg_catalog') ORDER BY 1, 2"
    ).fetchall()
    out: dict[str, list[object]] = {}
    for schema, name in tables:
        n, digest = con.execute(ROWS.format(table=f"{_quote(schema)}.{_quote(name)}")).fetchall()[0]
        (columns,) = con.execute(COLUMNS, [schema, name]).fetchall()[0]
        out[f"{schema}.{name}"] = [n, digest, columns]
    return out


def main() -> None:
    db = sys.argv[1] if len(sys.argv) > 1 else "data/ghostbus.duckdb"
    with duckdb.connect(db, read_only=True) as con:
        print(json.dumps(fingerprints(con), indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
