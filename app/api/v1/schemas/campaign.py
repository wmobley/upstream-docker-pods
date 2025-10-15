from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from app.api.v1.schemas.station import StationsListResponseItem


class CampaignsIn(BaseModel):
    name: str
    contact_name: str | None = None
    contact_email: str | None = None
    description: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    allocation: str | None = None

class CampaignCreateResponse(BaseModel):
    id: int

class Location(BaseModel):
    bbox_west: float | None = None
    bbox_east: float | None = None
    bbox_south: float | None = None
    bbox_north: float | None = None

class SummaryListCampaigns(BaseModel):
    sensor_types: List[str] | None = None
    variable_names: List[str] | None = None
    is_published: bool | None = None
    published_at: datetime | None = None

class ListCampaignsResponseItem(BaseModel):
    id: int
    name: str
    location: Location | None = None
    description: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    allocation: str | None = None
    summary: SummaryListCampaigns
    geometry: dict = Field(default_factory=dict, nullable=True)  # type: ignore[call-overload,type-arg]
    is_published: bool = False
    published_at: datetime | None = None

class ListCampaignsResponsePagination(BaseModel):
    items: list[ListCampaignsResponseItem]
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
    description: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    allocation: str | None = None
    location: Location | None = None
    summary: SummaryGetCampaign
    geometry: dict = Field(default_factory=dict, nullable=True)  # type: ignore[call-overload,type-arg]
    stations: list[StationsListResponseItem] = []
    is_published: bool = False
    published_at: datetime | None = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    allocation: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class PublishRequest(BaseModel):
    """Request schema for publishing campaigns, stations, or sensors."""
    cascade: bool = Field(
        default=False,
        description="If true, cascade publish to child resources (e.g., sensors when publishing station)"
    )
    force: bool = Field(
        default=False,
        description="If true, force publish even if already published"
    )


class PublishResponse(BaseModel):
    """Response schema for publish/unpublish operations."""
    success: bool
    message: str
    published_count: int = Field(default=0, description="Number of items published/unpublished")
    errors: List[str] = Field(default_factory=list, description="Any errors encountered")
    id: int | None = None
    type: str | None = None
    is_published: bool | None = None
    published_at: datetime | None = None
    cascaded_items: List[str] | None = None
