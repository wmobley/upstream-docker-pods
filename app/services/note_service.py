from typing import Optional

from fastapi import HTTPException, status
from geoalchemy2.shape import to_shape
from geojson_pydantic import Point
from shapely.geometry import mapping

from app.api.v1.schemas.note import NoteCreate, NoteCreateResponse, NoteItem, NoteUpdate, ListNotesResponse
from app.db.models.note import NoteScope
from app.db.repositories.note_repository import NoteRepository


class NoteService:
    def __init__(self, repo: NoteRepository):
        self.repo = repo

    def _location_to_point(self, location: object) -> Optional[Point]:
        # Deliberate departure from the SQL-level `ST_AsGeoJSON` conversion
        # used by measurements — see docs/design/2026-07-23-measurement-note-location.md.
        # Note lists are small, so converting the already-loaded WKBElement in
        # Python avoids restructuring every list query for a field only one
        # scope ever populates.
        if location is None:
            return None
        return Point(**mapping(to_shape(location)))  # type: ignore[arg-type]

    def _to_item(self, note: object) -> NoteItem:
        return NoteItem(
            id=note.noteid,  # type: ignore[attr-defined]
            scope=note.scope,  # type: ignore[attr-defined]
            content=note.content,  # type: ignore[attr-defined]
            created_by=note.created_by,  # type: ignore[attr-defined]
            created_at=note.created_at,  # type: ignore[attr-defined]
            campaign_id=note.campaign_id,  # type: ignore[attr-defined]
            station_id=note.station_id,  # type: ignore[attr-defined]
            sensor_id=note.sensor_id,  # type: ignore[attr-defined]
            measurement_id=note.measurement_id,  # type: ignore[attr-defined]
            location=self._location_to_point(note.location),  # type: ignore[attr-defined]
        )

    def create_campaign_note(
        self, request: NoteCreate, campaign_id: int, username: str
    ) -> NoteCreateResponse:
        note = self.repo.create(
            scope=NoteScope.CAMPAIGN,
            content=request.content,
            created_by=username,
            campaign_id=campaign_id,
        )
        return NoteCreateResponse(id=note.noteid)

    def create_station_note(
        self, request: NoteCreate, campaign_id: int, station_id: int, username: str
    ) -> NoteCreateResponse:
        note = self.repo.create(
            scope=NoteScope.STATION,
            content=request.content,
            created_by=username,
            campaign_id=campaign_id,
            station_id=station_id,
        )
        return NoteCreateResponse(id=note.noteid)

    def create_sensor_note(
        self, request: NoteCreate, campaign_id: int, station_id: int, sensor_id: int, username: str
    ) -> NoteCreateResponse:
        note = self.repo.create(
            scope=NoteScope.SENSOR,
            content=request.content,
            created_by=username,
            campaign_id=campaign_id,
            station_id=station_id,
            sensor_id=sensor_id,
        )
        return NoteCreateResponse(id=note.noteid)

    def create_measurement_note(
        self,
        request: NoteCreate,
        campaign_id: int,
        station_id: int,
        measurement_id: int,
        username: str,
        location: Optional[str] = None,
    ) -> NoteCreateResponse:
        note = self.repo.create(
            scope=NoteScope.MEASUREMENT,
            content=request.content,
            created_by=username,
            campaign_id=campaign_id,
            station_id=station_id,
            measurement_id=measurement_id,
            location=location,
        )
        return NoteCreateResponse(id=note.noteid)

    def list_campaign_notes(self, campaign_id: int) -> ListNotesResponse:
        notes, total = self.repo.list_by_campaign(campaign_id)
        return ListNotesResponse(items=[self._to_item(n) for n in notes], total=total)

    def list_station_notes(self, campaign_id: int, station_id: int) -> ListNotesResponse:
        notes, total = self.repo.list_by_station(campaign_id, station_id)
        return ListNotesResponse(items=[self._to_item(n) for n in notes], total=total)

    def list_sensor_notes(self, campaign_id: int, station_id: int, sensor_id: int) -> ListNotesResponse:
        notes, total = self.repo.list_by_sensor(campaign_id, station_id, sensor_id)
        return ListNotesResponse(items=[self._to_item(n) for n in notes], total=total)

    def list_measurement_notes(
        self, campaign_id: int, station_id: int, measurement_id: int
    ) -> ListNotesResponse:
        notes, total = self.repo.list_by_measurement(campaign_id, station_id, measurement_id)
        return ListNotesResponse(items=[self._to_item(n) for n in notes], total=total)

    def update(
        self,
        note_id: int,
        request: NoteUpdate,
        username: str,
        location: Optional[str] = None,
    ) -> NoteItem:
        # Full-replacement semantics, matching `content`: whatever `location`
        # is passed becomes the note's new location (None clears it). Non-
        # measurement callers never pass this, so their (always-None) location
        # is a no-op. See docs/design/2026-07-23-measurement-note-location.md.
        note = self.repo.get(note_id)
        if not note:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
        if note.created_by != username:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot edit another user's note")
        updated = self.repo.update(note_id, request.content, location=location)
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
        return self._to_item(updated)

    def delete(self, note_id: int, username: str) -> None:
        note = self.repo.get(note_id)
        if not note:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
        if note.created_by != username:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot delete another user's note")
        self.repo.delete(note_id)
