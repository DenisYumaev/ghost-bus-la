"""Copy gold tables from the DuckDB warehouse into Postgres `serving`, one atomic swap per table.

Pipeline spec section 13 and ADR-007. For each table:

1. Read the source query from DuckDB (read-only) and refuse NULL keys.
2. Create `serving.<name>__new` (dropping any left by a crash), COPY the rows in, then build the
   primary key and indexes. The API never sees this table.
3. Refuse a load more than 20% away from the last successful one, or an empty one, unless
   `force` (row_count_problem).
4. In one transaction: rename the live table to `__old`, rename `__new` to the live name, drop
   `__old`, and record the load in `ops.publish_run`. Readers see the old table or the new one,
   never a mix; if anything in the transaction fails, all of it rolls back.

A failed table leaves the live table as it was, drops its staging table, records a failed run,
and doesn't stop the other tables; publish raises PublishError at the end if any failed.
Constraint and index names carry a per-run suffix so repeated swaps never collide.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import psycopg
from psycopg import sql

PG_TYPES = {
    "VARCHAR": "text",
    "INTEGER": "integer",
    "BIGINT": "bigint",
    "DOUBLE": "double precision",
    "BOOLEAN": "boolean",
    "DATE": "date",
    "TIMESTAMP WITH TIME ZONE": "timestamptz",
}
MAX_CHANGE = 0.2  # pipeline spec section 13


@dataclass(frozen=True)
class ServingTable:
    """One serving table: its DuckDB source query, primary key and extra indexes."""

    name: str
    source_sql: str
    key: tuple[str, ...]
    indexes: tuple[tuple[str, ...], ...] = ()
    # Key columns allowed to be NULL (then the key is a unique index, not a primary key).
    nullable_key: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Result:
    table: str
    row_count: int


class PublishError(Exception):
    """One or more tables failed; the message names each and why."""


def pg_type(duck_type: str) -> str:
    try:
        return PG_TYPES[duck_type]
    except KeyError:
        raise ValueError(f"no Postgres type for DuckDB {duck_type}: add it to PG_TYPES") from None


def create_table_sql(table: ServingTable, columns: Sequence[tuple[str, str]]) -> str:
    cols = ", ".join(f'"{name}" {pg_type(duck)}' for name, duck in columns)
    return f'CREATE TABLE serving."{table.name}__new" ({cols})'


def row_count_problem(previous: int | None, new: int, *, force: bool) -> str | None:
    """Why a load of `new` rows mustn't replace one of `previous` rows, or None if it may."""
    if force:
        return None
    if new == 0:
        return "no rows"
    if previous is not None and abs(new - previous) > MAX_CHANGE * previous:
        return f"{new} rows against {previous} last time (more than {MAX_CHANGE:.0%} apart)"
    return None


def publish(
    warehouse: Path,
    database_url: str,
    tables: Sequence[ServingTable],
    *,
    source: str,
    force: bool = False,
) -> list[Result]:
    run_id = uuid.uuid4()
    results: list[Result] = []
    failures: list[str] = []
    with (
        duckdb.connect(str(warehouse), read_only=True) as duck,
        psycopg.connect(database_url.replace("postgresql+psycopg://", "postgresql://")) as pg,
    ):
        for table in tables:
            with pg.cursor() as cur:
                cur.execute("SELECT clock_timestamp()")
                started = cur.fetchone()[0]  # type: ignore[index]
            pg.commit()
            try:
                n = _publish_table(duck, pg, table, run_id, source, started, force)
                results.append(Result(table.name, n))
            except Exception as exc:
                pg.rollback()
                failures.append(f"{table.name}: {exc}")
                _record_failure(pg, table, run_id, source, started, str(exc))
    if failures:
        raise PublishError("; ".join(failures))
    return results


def _publish_table(
    duck: duckdb.DuckDBPyConnection,
    pg: psycopg.Connection,
    table: ServingTable,
    run_id: uuid.UUID,
    source: str,
    started: object,
    force: bool,
) -> int:
    columns = [(r[0], r[1]) for r in duck.execute(f"DESCRIBE {table.source_sql}").fetchall()]
    strict = [k for k in table.key if k not in table.nullable_key]
    if strict:
        # Source SQL and key names come from this package's code, never from input.
        where = " OR ".join(f'"{k}" IS NULL' for k in strict)
        nulls_sql = f"SELECT count(*) FROM ({table.source_sql}) WHERE {where}"  # noqa: S608
        (nulls,) = duck.execute(nulls_sql).fetchall()[0]
        if nulls:
            raise ValueError(f"{nulls} rows with a NULL key ({', '.join(strict)})")
    new = sql.Identifier(f"{table.name}__new")
    live = sql.Identifier(table.name)
    old = sql.Identifier(f"{table.name}__old")
    suffix = run_id.hex[:8]
    n = 0
    with pg.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS serving.{}").format(new))
        cur.execute(create_table_sql(table, columns).encode())
        names = sql.SQL(", ").join(sql.Identifier(c) for c, _ in columns)
        copy_sql = sql.SQL("COPY serving.{} ({}) FROM STDIN").format(new, names)
        result = duck.execute(table.source_sql)
        with cur.copy(copy_sql) as copy:
            while batch := result.fetchmany(10_000):
                for row in batch:
                    copy.write_row(row)
                n += len(batch)
        key = sql.SQL(", ").join(sql.Identifier(k) for k in table.key)
        if table.nullable_key:
            unique = sql.SQL("CREATE UNIQUE INDEX {} ON serving.{} ({}) NULLS NOT DISTINCT")
            cur.execute(unique.format(sql.Identifier(f"{table.name}_key_{suffix}"), new, key))
        else:
            cur.execute(sql.SQL("ALTER TABLE serving.{} ADD CONSTRAINT {} PRIMARY KEY ({})")
                        .format(new, sql.Identifier(f"{table.name}_pk_{suffix}"), key))  # fmt: skip
        for i, cols in enumerate(table.indexes):
            cur.execute(sql.SQL("CREATE INDEX {} ON serving.{} ({})").format(
                sql.Identifier(f"{table.name}_ix{i}_{suffix}"), new,
                sql.SQL(", ").join(sql.Identifier(c) for c in cols)))  # fmt: skip
        cur.execute(
            "SELECT row_count FROM ops.publish_run WHERE table_name = %s AND status = 'succeeded'"
            " ORDER BY finished_at DESC, id DESC LIMIT 1",
            (table.name,),
        )
        last = cur.fetchone()
        problem = row_count_problem(last[0] if last else None, n, force=force)
        if problem:
            raise ValueError(problem)
    pg.commit()  # the staging table is complete; now swap in one transaction
    with pg.transaction(), pg.cursor() as cur:
        cur.execute(sql.SQL("ALTER TABLE IF EXISTS serving.{} RENAME TO {}").format(live, old))
        cur.execute(sql.SQL("ALTER TABLE serving.{} RENAME TO {}").format(new, live))
        cur.execute(sql.SQL("DROP TABLE IF EXISTS serving.{}").format(old))
        cur.execute(
            "INSERT INTO ops.publish_run (run_id, table_name, status, row_count, source,"
            " started_at) VALUES (%s, %s, 'succeeded', %s, %s, %s)",
            (run_id, table.name, n, source, started),
        )
    return n


def _record_failure(
    pg: psycopg.Connection,
    table: ServingTable,
    run_id: uuid.UUID,
    source: str,
    started: object,
    error: str,
) -> None:
    """Drop the staging table and record the failed run (best effort: a table name ops refuses
    is itself a failure the caller already reports)."""
    try:
        with pg.transaction(), pg.cursor() as cur:
            cur.execute(
                sql.SQL("DROP TABLE IF EXISTS serving.{}").format(
                    sql.Identifier(f"{table.name}__new")
                )
            )
        with pg.transaction(), pg.cursor() as cur:
            cur.execute(
                "INSERT INTO ops.publish_run (run_id, table_name, status, row_count, source,"
                " started_at, error) VALUES (%s, %s, 'failed', NULL, %s, %s, %s)",
                (run_id, table.name, source, started, error[:2000] or "unknown error"),
            )
    except psycopg.Error:
        pg.rollback()
