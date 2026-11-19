"""Line endpoints (API spec section 4.1). No SQL here: repositories own the queries."""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from ghostbus_api.caching import CACHE_CONTROL, etag_for, matches
from ghostbus_api.problems import Problem
from ghostbus_api.repos import lines as repo
from ghostbus_api.schemas.reliability import DayType, LineReliability, ReliabilityCell, Window

router = APIRouter(prefix="/v1")


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
    today = request.app.state.today()
    with request.app.state.engine.connect() as con:
        found = repo.find_line(con, line, today)
        if found is None:
            raise Problem(404, "Line not found", f"No line '{line}'.")
        headsign = repo.find_direction(con, found["schedule_version"], found["line"], direction_id)
        if headsign is None or not repo.has_cells(con, found["line"], direction_id):
            raise Problem(404, "Direction not found", f"No data for direction {direction_id}.")
        as_of = repo.data_as_of(con, "reliability")
        if as_of is None:
            raise Problem(503, "No published data yet")
        # The tag covers everything the response shows: the grid's publish, the line tables'
        # publishes (headsign, name) and the schedule version in force, which can change at
        # midnight with no publish at all.
        versions = [repo.data_as_of(con, t) for t in ("line", "line_direction")]
        newest = max([as_of, *[v for v in versions if v]])
        key = dict(request.query_params) | {"_version": found["schedule_version"]}
        tag = etag_for(newest, request.url.path, key)
        headers = {"ETag": tag, "Cache-Control": CACHE_CONTROL}
        if matches(request.headers.get("if-none-match"), tag):
            return Response(status_code=304, headers=headers)
        rows = repo.reliability_cells(con, found["line"], direction_id, window, day_type)
        bounds = repo.window_bounds(con, window) or {}
    body = LineReliability(
        line=found["line"],
        line_slug=found["line_slug"],
        display_name=found["display_name"],
        direction_id=direction_id,
        headsign=headsign,
        window=window,
        window_start=bounds.get("window_start"),
        data_through=bounds.get("window_end"),
        data_as_of=as_of,
        cells=[ReliabilityCell(**{k: r[k] for k in ReliabilityCell.model_fields}) for r in rows],
        method_url=f"{request.app.state.settings.site_url}/method",
    )
    return Response(body.model_dump_json(), media_type="application/json", headers=headers)
