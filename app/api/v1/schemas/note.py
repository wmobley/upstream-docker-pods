from datetime import datetime
from typing import List

from pydantic import BaseModel

from app.db.models.note import NoteScope


class NoteCreate(BaseModel):
    content: str


class NoteUpdate(BaseModel):
    content: str


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

    model_config = {"from_attributes": True}


class NoteCreateResponse(BaseModel):
    id: int


class ListNotesResponse(BaseModel):
    items: List[NoteItem]
    total: int
