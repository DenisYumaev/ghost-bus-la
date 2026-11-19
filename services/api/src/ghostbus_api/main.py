"""The app factory (API spec section 10)."""

from fastapi import FastAPI

from ghostbus_api import problems
from ghostbus_api.db import make_engine
from ghostbus_api.routers import health, lines
from ghostbus_api.settings import Settings, from_env


def create_app(database_url: str | None = None) -> FastAPI:
    settings = Settings(database_url=database_url) if database_url else from_env()
    app = FastAPI(
        title="Ghost Bus LA API",
        description="Reliability of LA Metro bus lines. Not affiliated with LA Metro.",
        version="0.1.0",
        openapi_url="/v1/openapi.json",
        docs_url="/v1/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    problems.install(app)
    app.include_router(health.router)
    app.include_router(lines.router)
    return app
