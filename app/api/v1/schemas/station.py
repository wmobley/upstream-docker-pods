from datetime import datetime
from enum import Enum
from typing import Optional, List, Union
from pydantic import BaseModel

from app.api.v1.schemas.sensor import SensorItem
from geojson_pydantic.geometries import Geometry

class StationCreateResponse(BaseModel):
    id: int

class StationType(str, Enum):
    MOBILE = "mobile"
    STATIC = "static"

class StationCreate(BaseModel):
    name: str
    description: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    active: Optional[bool] = True
    start_date: datetime
    station_type: StationType  = StationType.STATIC

class StationItem(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    active: Optional[bool] = None
    start_date: Optional[datetime] = None
    geometry: Optional[Geometry] = None

class StationItemWithSummary(StationItem):
    sensor_count: int
    sensor_types: List[str]
    sensor_variables: List[str]

class GetStationResponse(StationItem):
    sensors: Optional[List[SensorItem]] = None

class ListStationsResponsePagination(BaseModel):
    items: List[StationItemWithSummary]
    total: int
    page: int
    size: int
    pages: int

class SensorSummaryForStations(BaseModel):
    id: int
    variable_name: Optional[str] = None
    measurement_unit: Optional[str] = None

class StationsListResponseItem(StationItem):
    start_date: datetime
    sensors: List[SensorSummaryForStations] = []



class StationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    active: Optional[bool] = None
    start_date: Optional[datetime] = None
    station_type: Optional[StationType] = None