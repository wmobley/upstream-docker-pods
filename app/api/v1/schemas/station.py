from datetime import datetime
from enum import Enum
from typing import Any, Optional, List
from pydantic import BaseModel, Field

from app.api.v1.schemas.sensor import SensorItem

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
    station_type: StationType  = StationType.STATIC

class StationItem(BaseModel):
    id: int
    name: str
    description: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    active: bool | None = None
    start_date: datetime | None = None
    geometry: dict = Field(default_factory=dict, nullable=True)  # type: ignore[call-overload,type-arg]

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
    station_type: Optional[StationType] | None  = None