from datetime import datetime
from typing import List, Optional, Union

from pydantic import BaseModel

from geojson_pydantic.geometries import Geometry
from app.api.v1.schemas.station import StationsListResponseItem


class CampaignsIn(BaseModel):
    name: str
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    allocation: str

class CampaignCreateResponse(BaseModel):
    id: int

class Location(BaseModel):
    bbox_west: Optional[float] = None
    bbox_east: Optional[float] = None
    bbox_south: Optional[float] = None
    bbox_north: Optional[float] = None

class SummaryListCampaigns(BaseModel):
    sensor_types: Optional[List[str]] = None
    variable_names: Optional[List[str]] = None

class ListCampaignsResponseItem(BaseModel):
    id: int
    name: str
    location: Optional[Location] = None
    description: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    allocation: Optional[str] = None
    summary: SummaryListCampaigns
    geometry: Optional[Geometry] = None

class ListCampaignsResponsePagination(BaseModel):
    items: List[ListCampaignsResponseItem]
    total: int
    page: int
    size: int
    pages: int

class SummaryGetCampaign(BaseModel):
    station_count: int
    sensor_count: int
    sensor_types: List[str]
    sensor_variables: List[str]

class GetCampaignResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    allocation: str
    location: Optional[Location] = None
    summary: SummaryGetCampaign
    geometry: Optional[Geometry] = None
    stations: List[StationsListResponseItem] = []


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    allocation: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None