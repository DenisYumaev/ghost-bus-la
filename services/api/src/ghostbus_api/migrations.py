"""Run Alembic migrations from code (deploy script, tests) without an alembic.ini.

The migration scripts live in `ghostbus_api/alembic/` so they ship inside the API image.
The database URL comes from the caller; it is never read from a committed file.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

SCRIPT_LOCATION = Path(__file__).parent / "alembic"


def _config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(SCRIPT_LOCATION))
    # Alembic's config uses %-interpolation; escape any % in a password.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_to_head(database_url: str) -> None:
    command.upgrade(_config(database_url), "head")


def downgrade_to_base(database_url: str) -> None:
    command.downgrade(_config(database_url), "base")
