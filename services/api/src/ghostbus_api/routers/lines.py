"""Line endpoints (API spec section 4.1). No SQL here: repositories own the queries."""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from ghostbus_api.caching import CACHE_CONTROL, etag_for
from ghostbus_api.problems import Problem
from ghostbus_api.repos import lines as repo
from ghostbus_api.schemas.reliability import DayType, LineReliability, ReliabilityCell, Window

router = APIRouter(prefix="/v1")
LOCAL = ZoneInfo("America/Los_Angeles")


@router.get(
    "/lines/{line}/reliability",
    response_model=LineReliability,
    summary="Hour-by-day-type reliability grid for one line and direction",
    description=(
        "Rates for each day type and local hour of scheduled start over a window. `line` is "
        "the line slug (`720`, `10-48`). Cells with too few trips or days are suppressed: "
        "counts but no rates. `ci_low` and `ci_high` are the 95% interval for `missed_rate`."
    ),
)
def line_reliability(
    request: Request,
    line: str,
    direction_id: Annotated[int, Query(ge=0, le=1)],
    window: Window = "28d",
    day_type: DayType | None = None,
) -> Response:
    today = datetime.now(LOCAL).date()
    with request.app.state.engine.connect() as con:
        found = repo.find_line(con, line, today)
        if found is None:
            raise Problem(404, "Line not found", f"No line '{line}'.")
        headsign = repo.find_direction(con, found["line"], direction_id, today)
        if headsign is None or not repo.has_cells(con, found["line"], direction_id):
            raise Problem(404, "Direction not found", f"No data for direction {direction_id}.")
        as_of = repo.data_as_of(con, "reliability")
        if as_of is None:
            raise Problem(503, "No published data yet")
        tag = etag_for(as_of, request.url.path, dict(request.query_params))
        headers = {"ETag": tag, "Cache-Control": CACHE_CONTROL}
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers=headers)
        rows = repo.reliability_cells(con, found["line"], direction_id, window, day_type)
    first = rows[0] if rows else {}
    body = LineReliability(
        line=found["line"],
        line_slug=found["line_slug"],
        display_name=found["display_name"],
        direction_id=direction_id,
        headsign=headsign,
        window=window,
        window_start=first.get("window_start"),
        data_through=first.get("window_end"),
        data_as_of=as_of,
        cells=[ReliabilityCell(**{k: r[k] for k in ReliabilityCell.model_fields}) for r in rows],
        method_url=f"{request.app.state.settings.site_url}/method",
    )
    return Response(body.model_dump_json(), media_type="application/json", headers=headers)
