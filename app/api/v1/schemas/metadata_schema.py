from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MetadataSchemaBase(BaseModel):
    scope: str = Field(..., description="Scope for the metadata field (campaign, station, sensor)")
    key: str = Field(..., description="Unique key for this metadata field within the scope")
    label: str = Field(..., description="Human-readable label")
    field_type: str = Field(..., description="string | number | date | enum | bool | json")
    required: bool = False
    help_text: Optional[str] = None
    units: Optional[str] = None
    ckan_field: Optional[str] = None
    ckan_mode: str = "extra"
    order_index: int = 0
    active: bool = True
    options: Optional[Dict[str, Any]] = None


class MetadataSchemaCreate(MetadataSchemaBase):
    pass


class MetadataSchemaUpdate(BaseModel):
    scope: Optional[str] = None
    key: Optional[str] = None
    label: Optional[str] = None
    field_type: Optional[str] = None
    required: Optional[bool] = None
    help_text: Optional[str] = None
    units: Optional[str] = None
    ckan_field: Optional[str] = None
    ckan_mode: Optional[str] = None
    order_index: Optional[int] = None
    active: Optional[bool] = None
    options: Optional[Dict[str, Any]] = None


class MetadataSchemaResponse(MetadataSchemaBase):
    id: int


class MetadataSchemaListResponse(BaseModel):
    items: List[MetadataSchemaResponse]
