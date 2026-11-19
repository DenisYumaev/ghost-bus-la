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
and doesn't stop the other tables; publish raises PublishError at the end if any failed. (If
the Postgres connection itself drops, the run stops there with the connection's error.)
Only one publish runs at a time (an advisory lock). The swap waits at most SWAP_LOCK_TIMEOUT for
its exclusive lock, so a reader holding the table open makes it retry, then fail, never hang
while every new reader queues behind it. Failed runs also add ops.publish_run rows, so an API
that watches max(id) to clear its cache clears it once more than needed; data_as_of only
uses succeeded rows.
Constraint and index names carry a per-run suffix so repeated swaps never collide.
"""

import re
import time
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
# The swap needs an exclusive lock on the live table; a reader holding it open mustn't make the
# swap wait forever while every new API query queues behind it. Wait this long, then retry.
SWAP_LOCK_TIMEOUT = "2s"
SWAP_ATTEMPTS = 3
# One publish at a time: concurrent runs would drop each other's staging tables.
ADVISORY_LOCK = "ghostbus_publish"
# ops.publish_run's CHECK, and room for "<name>_ix9_<8 hex>" within Postgres's 63-byte names.
NAME = re.compile(r"^[a-z][a-z0-9_]{0,48}$")


@dataclass(frozen=True)
class ServingTable:
    """One serving table: its DuckDB source query, primary key and extra indexes."""

    name: str
    source_sql: str
    key: tuple[str, ...]
    indexes: tuple[tuple[str, ...], ...] = ()
    # Key columns allowed to be NULL (then the key is a unique index, not a primary key).
    nullable_key: frozenset[str] = field(default_factory=frozenset)
    # The row-count guard's limit; None for tables that legitimately grow in steps (every
    # schedule version ever in force; a weekly trend in its first weeks), where a refusal would
    # only force operators to switch the guard off for every table.
    max_change: float | None = MAX_CHANGE
    # An empty load is refused unless the table can legitimately be empty (current
    # cancellations overnight).
    allow_empty: bool = False
    # Published by a plain `make publish`? Tables built only by the open-date build (current
    # cancellations) are published by it alone, with --only: a closed-date build would replace
    # the live list with an empty one.
    default: bool = True

    def __post_init__(self) -> None:
        if not NAME.match(self.name) or self.name.endswith(("__new", "__old")):
            raise ValueError(f"bad serving table name {self.name!r}: lowercase, at most 49 chars")


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


def create_table_sql(table: ServingTable, columns: Sequence[tuple[str, str]]) -> sql.Composed:
    cols = sql.SQL(", ").join(
        sql.SQL("{} {}").format(sql.Identifier(name), sql.SQL(pg_type(duck)))
        for name, duck in columns
    )
    return sql.SQL("CREATE TABLE serving.{} ({})").format(
        sql.Identifier(f"{table.name}__new"), cols
    )


def row_count_problem(
    previous: int | None,
    new: int,
    *,
    force: bool,
    max_change: float | None = MAX_CHANGE,
    allow_empty: bool = False,
) -> str | None:
    """Why a load of `new` rows mustn't replace one of `previous` rows, or None if it may."""
    if force:
        return None
    if new == 0:
        return None if allow_empty else "no rows"
    # previous 0 is a forced empty load: no baseline.
    if max_change is not None and previous and abs(new - previous) > max_change * previous:
        return f"{new} rows against {previous} last time (more than {max_change:.0%} apart)"
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
        with pg.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (ADVISORY_LOCK,))
            got = cur.fetchone()
        pg.commit()
        if not (got and got[0]):
            raise PublishError("another publish run holds the lock; not starting")
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
        cur.execute(create_table_sql(table, columns))
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
        problem = row_count_problem(
            last[0] if last else None, n, force=force, max_change=table.max_change,
            allow_empty=table.allow_empty,
        )  # fmt: skip
        if problem:
            raise ValueError(problem)
        # Column statistics now, so the first API query on the new table plans well.
        cur.execute(sql.SQL("ANALYZE serving.{}").format(new))
    pg.commit()  # the staging table is complete; now swap in one transaction
    for attempt in range(1, SWAP_ATTEMPTS + 1):
        try:
            with pg.transaction(), pg.cursor() as cur:
                cur.execute(f"SET LOCAL lock_timeout = '{SWAP_LOCK_TIMEOUT}'")
                # A stray __old (a manual repair) would make the first rename fail every run.
                cur.execute(sql.SQL("DROP TABLE IF EXISTS serving.{}").format(old))
                cur.execute(
                    sql.SQL("ALTER TABLE IF EXISTS serving.{} RENAME TO {}").format(live, old)
                )
                cur.execute(sql.SQL("ALTER TABLE serving.{} RENAME TO {}").format(new, live))
                cur.execute(sql.SQL("DROP TABLE IF EXISTS serving.{}").format(old))
                cur.execute(
                    "INSERT INTO ops.publish_run (run_id, table_name, status, row_count, source,"
                    " started_at) VALUES (%s, %s, 'succeeded', %s, %s, %s)",
                    (run_id, table.name, n, source, started),
                )
            return n
        except psycopg.errors.LockNotAvailable:
            if attempt == SWAP_ATTEMPTS:
                raise
            time.sleep(attempt)
    raise AssertionError("unreachable")


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
