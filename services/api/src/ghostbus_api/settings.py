"""Settings from the environment (never from files in the repo; hard rule 9)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    # The public site, for links in responses (method page, problem types).
    site_url: str = "http://localhost:3000"
    # /readyz fails when the newest successful publish is older than this (API spec 4.4).
    max_data_age_minutes: int = 60


def from_env() -> Settings:
    url = os.environ.get("GHOSTBUS_DATABASE_URL")
    if not url:
        raise RuntimeError("GHOSTBUS_DATABASE_URL is not set")
    return Settings(
        database_url=url, site_url=os.environ.get("GHOSTBUS_SITE_URL", Settings.site_url)
    )
