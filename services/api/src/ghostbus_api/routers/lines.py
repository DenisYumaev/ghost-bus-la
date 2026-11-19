"""Line endpoints (API spec section 4.1). No SQL here: repositories own the queries."""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from ghostbus_api.problems import Problem
from ghostbus_api.repos import lines as repo
from ghostbus_api.routers._http import conditional, json_response
from ghostbus_api.schemas.common import Rates
from ghostbus_api.schemas.lines import Direction, LineDetail, LineList, LineListItem, Stop, StopList
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
        # The grid's publish, the line tables (headsign, name) and the version in force, which
        # can change at midnight with no publish at all.
        as_of, headers, not_modified = conditional(
            request, con, ("reliability", "line", "line_direction", "system_summary"),
            {"_version": found["schedule_version"]},
        )  # fmt: skip
        if not_modified:
            return not_modified
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
    return json_response(body, headers)


LINE_TABLES = ("line", "line_direction")


def _find(con: object, request: Request, line: str) -> dict[str, object]:
    found = repo.find_line(con, line, request.app.state.today())  # type: ignore[arg-type]
    if found is None:
        raise Problem(404, "Line not found", f"No line '{line}'.")
    return found


@router.get(
    "/lines",
    response_model=LineList,
    summary="All lines with their headline reliability",
    description=(
        "Every line in the schedule in force today, with its summary over the window (default "
        "28 days), both directions pooled. Suppressed lines have counts but no rates."
    ),
)
def list_lines(request: Request, window: Window = "28d") -> Response:
    today = request.app.state.today()
    with request.app.state.engine.connect() as con:
        as_of, headers, not_modified = conditional(
            request, con, ("line_summary", "line", "schedule_version", "system_summary"),
            {"_today": today.isoformat()},
        )  # fmt: skip
        if not_modified:
            return not_modified
        rows = repo.list_lines(con, today, window)
        bounds = repo.window_bounds(con, window) or {}
    body = LineList(
        window=window,
        window_start=bounds.get("window_start"),
        data_through=bounds.get("window_end"),
        data_as_of=as_of,
        lines=[
            LineListItem(
                line=r["line"], line_slug=r["line_slug"], display_name=r["display_name"],
                line_kind=r["line_kind"], summary=Rates.from_row(r),
            )
            for r in rows
        ],
    )  # fmt: skip
    return json_response(body, headers)


@router.get(
    "/lines/{line}",
    response_model=LineDetail,
    summary="One line: name, directions with headsigns, summary rates",
    description="`line` is the line slug. Summaries are over the window (default 28 days).",
)
def line_detail(request: Request, line: str, window: Window = "28d") -> Response:
    with request.app.state.engine.connect() as con:
        found = _find(con, request, line)
        as_of, headers, not_modified = conditional(
            request, con, ("line_summary", *LINE_TABLES, "system_summary"),
            {"_version": str(found["schedule_version"])},
        )  # fmt: skip
        if not_modified:
            return not_modified
        info = repo.line_info(con, str(found["schedule_version"]), str(found["line"]))
        dirs = repo.directions(con, str(found["schedule_version"]), str(found["line"]))
        summaries = {
            r["direction_id"]: r for r in repo.line_summaries(con, str(found["line"]), window)
        }
        bounds = repo.window_bounds(con, window) or {}
    body = LineDetail(
        line=str(found["line"]), line_slug=str(found["line_slug"]),
        display_name=str(found["display_name"]), window=window,
        data_through=bounds.get("window_end"), data_as_of=as_of,
        summary=Rates.from_row(summaries.get(None)),
        directions=[
            Direction(**d, summary=Rates.from_row(summaries.get(d["direction_id"]))) for d in dirs
        ],
        **info,
    )  # fmt: skip
    return json_response(body, headers)


@router.get(
    "/lines/{line}/stops",
    response_model=StopList,
    summary="Ordered stops for one direction",
    description=(
        "Every stop the direction serves in the schedule in force today, in route order "
        "(branches and short turns placed between the trunk stops around them)."
    ),
)
def line_stops(
    request: Request, line: str, direction_id: Annotated[int, Query(ge=0, le=1)]
) -> Response:
    with request.app.state.engine.connect() as con:
        found = _find(con, request, line)
        version, name = str(found["schedule_version"]), str(found["line"])
        headsign = repo.find_direction(con, version, name, direction_id)
        if headsign is None:
            raise Problem(404, "Direction not found", f"No direction {direction_id}.")
        as_of, headers, not_modified = conditional(
            request, con, ("line_stop", *LINE_TABLES), {"_version": version}
        )
        if not_modified:
            return not_modified
        rows = repo.stops(con, version, name, direction_id)
        if not rows:  # the direction exists, so its stops are still being published
            raise Problem(503, "Stops not published yet")
    body = StopList(
        line=name, line_slug=str(found["line_slug"]), direction_id=direction_id,
        headsign=headsign, data_as_of=as_of, stops=[Stop(**r) for r in rows],
    )  # fmt: skip
    return json_response(body, headers)
