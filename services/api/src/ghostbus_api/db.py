"""The pooled engine (ADR-013): sync SQLAlchemy Core over psycopg 3, with server-side timeouts
so a runaway query can't hold a worker and a forgotten transaction can't hold the serving-table
locks that publish's swap waits for (ADR-007)."""

from sqlalchemy import Engine, create_engine

STATEMENT_TIMEOUT_MS = 5_000
IDLE_IN_TRANSACTION_TIMEOUT_MS = 10_000


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return create_engine(
        database_url,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        connect_args={
            "options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS}"
            f" -c idle_in_transaction_session_timeout={IDLE_IN_TRANSACTION_TIMEOUT_MS}",
            "application_name": "ghostbus-api",
        },
    )
