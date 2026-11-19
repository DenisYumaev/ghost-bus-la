"""Operations endpoints (API spec section 4.4)."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from ghostbus_api.problems import problem_response
from ghostbus_api.repos.lines import stalest_publish

router = APIRouter()


@router.get("/healthz", summary="The process is up", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Database reachable and serving data fresh", include_in_schema=False)
def readyz(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    try:
        with request.app.state.engine.connect() as con:
            newest = stalest_publish(con)
    except SQLAlchemyError:
        return problem_response(request, 503, "Database unavailable")
    limit = timedelta(minutes=settings.max_data_age_minutes)
    if newest is None or datetime.now(UTC) - newest > limit:
        return problem_response(
            request, 503, "Serving data is stale",
            f"a serving table's last successful publish is older than "
            f"{settings.max_data_age_minutes} minutes",
        )  # fmt: skip
    return JSONResponse({"status": "ready", "data_as_of": newest.strftime("%Y-%m-%dT%H:%M:%SZ")})
