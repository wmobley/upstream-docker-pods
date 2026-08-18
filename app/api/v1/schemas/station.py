from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from zoneinfo import available_timezones

from pydantic import BaseModel, Field, field_validator

from app.api.v1.schemas.sensor import SensorItem

_AVAILABLE_TIMEZONES = available_timezones()


def _validate_iana_timezone(value: str) -> str:
    if value not in _AVAILABLE_TIMEZONES:
        raise ValueError(f"Invalid IANA timezone name: {value!r}")
    return value


class StationCreateResponse(BaseModel):
    id: int


class StationType(str, Enum):
    MOBILE = "mobile"
    STATIC = "static"


class StationCreate(BaseModel):
    name: str
    description: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    active: bool | None = True
    start_date: datetime
    station_type: StationType = StationType.STATIC
    timezone: str
    metadata: Dict[str, Any] | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return _validate_iana_timezone(value)


class StationItem(BaseModel):
    id: int
    name: str
    description: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    active: bool | None = None
    start_date: datetime | None = None
    station_type: StationType = StationType.STATIC
    timezone: str
    geometry: dict = Field(default_factory=dict, nullable=True)  # type: ignore[call-overload,type-arg]
    is_published: bool = False
    published_at: datetime | None = None
    metadata: Dict[str, Any] | None = None


class StationItemWithSummary(StationItem):
    sensor_count: int
    sensor_types: List[str]
    sensor_variables: List[str]


class GetStationResponse(StationItem):
    sensors: List[SensorItem] | None = None


class ListStationsResponsePagination(BaseModel):
    items: List[StationItemWithSummary]
    total: int
    page: int
    size: int
    pages: int


class SensorSummaryForStations(BaseModel):
    id: int
    variable_name: str | None = None
    measurement_unit: str | None = None


class StationsListResponseItem(StationItem):
    start_date: datetime
    sensors: List[SensorSummaryForStations] = []


class StationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] | None = None
    contact_name: Optional[str] | None = None
    contact_email: Optional[str] | None = None
    active: Optional[bool] | None = None
    start_date: Optional[datetime] | None = None
    station_type: Optional[StationType] | None = None
    timezone: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _validate_iana_timezone(value)
