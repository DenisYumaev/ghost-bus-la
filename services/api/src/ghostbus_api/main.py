"""The app factory (API spec section 10)."""

from collections.abc import Callable
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from ghostbus_api import problems
from ghostbus_api.db import make_engine
from ghostbus_api.routers import cancellations, health, lines, meta, system, trips
from ghostbus_api.settings import Settings, from_env


def los_angeles_today() -> date:
    """The rider's local date (hard rule 5; ADR-028)."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()


def create_app(
    database_url: str | None = None, today: Callable[[], date] = los_angeles_today
) -> FastAPI:
    settings = Settings(database_url=database_url) if database_url else from_env()
    app = FastAPI(
        title="LA Bus Reliability API",
        description=(
            "Reliability of LA Metro bus lines. Not affiliated with LA Metro. "
            "Examples in this document are illustrative, not measured."
        ),
        version="0.1.0",
        openapi_url="/v1/openapi.json",
        docs_url="/v1/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.today = today  # injectable, so tests can pin the date
    problems.install(app)
    app.include_router(health.router)
    app.include_router(lines.router)
    app.include_router(system.router)
    app.include_router(trips.router)
    app.include_router(meta.router)
    app.include_router(cancellations.router)
    return app
