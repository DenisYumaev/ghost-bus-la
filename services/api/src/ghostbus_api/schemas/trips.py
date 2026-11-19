"""Response shapes for the trend and trip outcomes (API spec section 4.1)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel

from ghostbus_api.schemas import examples
from ghostbus_api.schemas.common import UtcTime


class TrendPoint(BaseModel):
    week_start: date
    n_service_days: int | None
    n_scheduled: int | None
    n_unknown: int | None
    n_trips: int | None
    n_ran: int | None
    n_partial: int | None
    n_missed: int | None
    n_missed_announced: int | None
    n_missed_unplanned: int | None
    missed_rate: float | None
    announced_rate: float | None
    unplanned_rate: float | None
    suppressed: bool  # true for an empty week too


class Trend(BaseModel):
    model_config = examples.examples(examples.TREND)

    line: str
    line_slug: str
    direction_id: int
    headsign: str
    weeks: int
    data_as_of: UtcTime
    points: list[TrendPoint]


class TripOutcome(BaseModel):
    trip_id: str
    direction_id: int | None
    sched_start: UtcTime
    sched_start_local: str  # HH:MM in Los Angeles (API spec section 1)
    outcome: Literal["ran", "partial", "missed", "unknown"]
    announced: bool
    advance_notice_s: float | None
    stop_coverage: float | None


class TripOutcomes(BaseModel):
    model_config = examples.examples(examples.TRIP_OUTCOMES)

    line: str
    line_slug: str
    service_date: date
    data_as_of: UtcTime
    trips: list[TripOutcome]
    next_cursor: str | None
