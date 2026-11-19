"""The method page's data (API spec section 4.1)."""

from pydantic import BaseModel

from ghostbus_api.schemas.common import UtcTime


class Threshold(BaseModel):
    name: str
    value: str
    unit: str
    description: str
    decision: str  # the ADR or spec section that set it


class Definition(BaseModel):
    term: str
    meaning: str


class Method(BaseModel):
    data_as_of: UtcTime
    thresholds: list[Threshold]
    outcomes: list[Definition]
    rates: list[Definition]
    notes: list[str]
