"""System-wide endpoints (API spec section 4.1)."""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from ghostbus_api.repos import system as repo
from ghostbus_api.routers._http import conditional, json_response
from ghostbus_api.schemas.common import Rates
from ghostbus_api.schemas.system import FeedBucket, FeedHealth, SystemSummary, WindowSummary

router = APIRouter(prefix="/v1/system")


@router.get(
    "/summary",
    response_model=SystemSummary,
    summary="Headline numbers, counts and date range",
    description=(
        "Pooled counts and rates for every trip in scope, per window. Internal until M5 "
        "validates them against Metro's report; suppressed until enough days are in."
    ),
)
def system_summary(request: Request) -> Response:
    with request.app.state.engine.connect() as con:
        as_of, headers, not_modified = conditional(request, con, ("system_summary",))
        if not_modified:
            return not_modified
        rows = repo.summaries(con)
    body = SystemSummary(
        data_as_of=as_of,
        windows=[
            WindowSummary(
                window=r["time_window"], window_start=r["window_start"],
                data_through=r["window_end"], first_data_date=r["first_data_date"],
                n_lines=r["n_lines"], rates=Rates.from_row(r),
            )
            for r in rows
        ],
    )  # fmt: skip
    return json_response(body, headers)


@router.get(
    "/feed-health",
    response_model=FeedHealth,
    summary="Feed status for the status page",
    description=(
        "Five-minute buckets per realtime feed over the last `hours` (default 24, at most 168), "
        "counted back from the newest bucket published. A bucket is healthy if a fetch "
        "succeeded with data under 3 minutes old (ADR-024)."
    ),
)
def feed_health(request: Request, hours: Annotated[int, Query(ge=1, le=168)] = 24) -> Response:
    with request.app.state.engine.connect() as con:
        as_of, headers, not_modified = conditional(request, con, ("feed_health",))
        if not_modified:
            return not_modified
        rows = repo.feed_health(con, hours)
    body = FeedHealth(hours=hours, data_as_of=as_of, buckets=[FeedBucket(**r) for r in rows])
    return json_response(body, headers)
