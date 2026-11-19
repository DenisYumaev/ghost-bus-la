"""Response shapes for the system summary and feed health (API spec section 4.1)."""

from datetime import date

from pydantic import BaseModel

from ghostbus_api.schemas import examples
from ghostbus_api.schemas.common import Rates, UtcTime


class WindowSummary(BaseModel):
    window: str
    window_start: date | None
    data_through: date | None
    first_data_date: date | None
    n_lines: int
    rates: Rates


class SystemSummary(BaseModel):
    model_config = examples.examples(examples.SYSTEM_SUMMARY)

    data_as_of: UtcTime
    windows: list[WindowSummary]


class FeedBucket(BaseModel):
    feed: str
    bucket_start: UtcTime
    n_fetches: int
    n_success: int
    n_errors: int
    error_rate: float | None
    freshest_age_s: float | None
    healthy: bool


class FeedHealth(BaseModel):
    model_config = examples.examples(examples.FEED_HEALTH)

    hours: int
    data_as_of: UtcTime
    buckets: list[FeedBucket]
