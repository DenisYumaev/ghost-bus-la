"""Alembic environment: online migrations only, one transaction per run."""

from alembic import context
from sqlalchemy import create_engine

url = context.config.get_main_option("sqlalchemy.url")
if not url:
    raise RuntimeError("no database URL: call ghostbus_api.migrations with one")

engine = create_engine(url)
with engine.connect() as connection:
    context.configure(connection=connection, transaction_per_migration=False)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
