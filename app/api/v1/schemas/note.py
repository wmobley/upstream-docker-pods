from datetime import datetime
from typing import List, Optional

from geojson_pydantic import Point
from pydantic import BaseModel, Field

from app.db.models.note import NoteScope


class NoteCreate(BaseModel):
    content: str


class NoteUpdate(BaseModel):
    content: str


class MeasurementNoteCreate(NoteCreate):
    """Only measurement notes may carry an independent location — see
    docs/design/2026-07-23-measurement-note-location.md. Deliberately not on
    the base NoteCreate so campaign/station/sensor routes have no way to
    receive one."""

    location: Optional[str] = Field(
        default=None,
        description='Independent location in Well-Known Text (WKT) format, e.g. "POINT(longitude latitude)". Separate from the measurement\'s own location.',
        examples=["POINT(10.12345 20.54321)"],
    )


class MeasurementNoteUpdate(NoteUpdate):
    """Full-replacement semantics, matching `content` on the base NoteUpdate:
    always send the desired location, or omit/null to clear it."""

    location: Optional[str] = Field(
        default=None,
        description="Same as MeasurementNoteCreate.location. Omitted or null clears the note's location.",
        examples=["POINT(10.12345 20.54321)"],
    )


class NoteItem(BaseModel):
    id: int
    scope: NoteScope
    content: str
    created_by: str
    created_at: datetime
    campaign_id: int
    station_id: int | None = None
    sensor_id: int | None = None
    measurement_id: int | None = None
    location: Optional[Point] = None

    model_config = {"from_attributes": True}


class NoteCreateResponse(BaseModel):
    id: int


class ListNotesResponse(BaseModel):
    items: List[NoteItem]
    total: int
