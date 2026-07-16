from typing import Optional

from fastapi import HTTPException, status

from app.api.v1.schemas.note import NoteCreate, NoteCreateResponse, NoteItem, NoteUpdate, ListNotesResponse
from app.db.models.note import NoteScope
from app.db.repositories.note_repository import NoteRepository


class NoteService:
    def __init__(self, repo: NoteRepository):
        self.repo = repo

    def _to_item(self, note: object) -> NoteItem:
        return NoteItem(
            id=note.noteid,  # type: ignore[attr-defined]
            scope=note.scope,  # type: ignore[attr-defined]
            content=note.content,  # type: ignore[attr-defined]
            created_by=note.created_by,  # type: ignore[attr-defined]
            created_at=note.created_at,  # type: ignore[attr-defined]
            campaign_id=note.campaign_id,  # type: ignore[attr-defined]
            station_id=note.station_id,  # type: ignore[attr-defined]
            measurement_id=note.measurement_id,  # type: ignore[attr-defined]
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

    def create_measurement_note(
        self,
        request: NoteCreate,
        campaign_id: int,
        station_id: int,
        measurement_id: int,
        username: str,
    ) -> NoteCreateResponse:
        note = self.repo.create(
            scope=NoteScope.MEASUREMENT,
            content=request.content,
            created_by=username,
            campaign_id=campaign_id,
            station_id=station_id,
            measurement_id=measurement_id,
        )
        return NoteCreateResponse(id=note.noteid)

    def list_campaign_notes(self, campaign_id: int) -> ListNotesResponse:
        notes, total = self.repo.list_by_campaign(campaign_id)
        return ListNotesResponse(items=[self._to_item(n) for n in notes], total=total)

    def list_station_notes(self, campaign_id: int, station_id: int) -> ListNotesResponse:
        notes, total = self.repo.list_by_station(campaign_id, station_id)
        return ListNotesResponse(items=[self._to_item(n) for n in notes], total=total)

    def list_measurement_notes(
        self, campaign_id: int, station_id: int, measurement_id: int
    ) -> ListNotesResponse:
        notes, total = self.repo.list_by_measurement(campaign_id, station_id, measurement_id)
        return ListNotesResponse(items=[self._to_item(n) for n in notes], total=total)

    def update(self, note_id: int, request: NoteUpdate, username: str) -> NoteItem:
        note = self.repo.get(note_id)
        if not note:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
        if note.created_by != username:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot edit another user's note")
        updated = self.repo.update(note_id, request.content)
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
