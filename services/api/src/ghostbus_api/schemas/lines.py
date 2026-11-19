"""Response shapes for the line list, line detail and stops (API spec section 4.1)."""

from datetime import date

from pydantic import BaseModel

from ghostbus_api.schemas import examples
from ghostbus_api.schemas.common import Rates, UtcTime


class LineListItem(BaseModel):
    line: str
    line_slug: str
    display_name: str
    line_kind: str | None
    summary: Rates


class LineList(BaseModel):
    model_config = examples.examples(examples.LINE_LIST)

    window: str
    window_start: date | None
    data_through: date | None
    data_as_of: UtcTime
    lines: list[LineListItem]


class Direction(BaseModel):
    direction_id: int
    headsign: str
    first_stop_name: str | None
    last_stop_name: str | None
    summary: Rates


class LineDetail(BaseModel):
    model_config = examples.examples(examples.LINE_DETAIL)

    line: str
    line_slug: str
    display_name: str
    line_kind: str | None
    description: str | None
    route_color: str | None
    route_text_color: str | None
    window: str
    data_through: date | None
    data_as_of: UtcTime
    summary: Rates  # both directions
    directions: list[Direction]


class Stop(BaseModel):
    stop_order: int
    stop_id: str
    stop_code: str | None
    stop_name: str | None
    stop_lat: float | None
    stop_lon: float | None
    in_main_pattern: bool


class StopList(BaseModel):
    model_config = examples.examples(examples.STOP_LIST)

    line: str
    line_slug: str
    direction_id: int
    headsign: str
    data_as_of: UtcTime
    stops: list[Stop]
