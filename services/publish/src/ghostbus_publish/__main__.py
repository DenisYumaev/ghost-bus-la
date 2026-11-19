"""Publish the serving tables from the local dbt warehouse into Postgres.

    GHOSTBUS_DATABASE_URL=postgresql://... uv run python -m ghostbus_publish [--force] [--only T]

The database URL comes from the environment, never the command line (it holds a password;
CLAUDE.md hard rule 9). The run's source is the synced range in data/_sync.json. Exits 1 if any
table failed; the live tables of failed loads keep their previous data.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg

from ghostbus_publish.engine import PublishError, publish
from ghostbus_publish.tables import TABLES


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--warehouse", default="data/ghostbus.duckdb", type=Path)
    parser.add_argument("--sync-file", default="data/_sync.json", type=Path)
    parser.add_argument("--force", action="store_true", help="skip the 20%% row-count guard")
    parser.add_argument("--only", action="append", help="publish only this table (repeatable)")
    args = parser.parse_args()
    url = os.environ.get("GHOSTBUS_DATABASE_URL")
    if not url:
        sys.exit("GHOSTBUS_DATABASE_URL is not set")
    synced = json.loads(args.sync_file.read_text())
    source = f"service dates {synced['start']}..{synced['end']}"
    if args.only:
        tables = [t for t in TABLES if t.name in args.only]
    else:  # tables every build publishes; open-date-only tables need --only (ADR-029)
        tables = [t for t in TABLES if t.default]
    unknown = set(args.only or []) - {t.name for t in TABLES}
    if unknown:
        sys.exit(f"unknown table(s): {', '.join(sorted(unknown))}")
    try:
        results = publish(args.warehouse, url, tables, source=source, force=args.force)
    except PublishError as exc:
        sys.exit(f"publish failed: {exc}")
    except psycopg.Error:
        # libpq's errors can quote the URL, password included (hard rule 9): say nothing more.
        sys.exit("cannot connect with GHOSTBUS_DATABASE_URL (check the URL); details withheld")
    for r in results:
        print(f"{r.table}: {r.row_count:,} rows")


if __name__ == "__main__":
    main()
