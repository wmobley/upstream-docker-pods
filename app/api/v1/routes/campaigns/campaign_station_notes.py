from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_edit_user, get_viewer_user
from app.api.v1.schemas.note import NoteCreate, NoteCreateResponse, NoteItem, NoteUpdate, ListNotesResponse
from app.api.v1.schemas.user import User
from app.db.session import get_db
from app.db.repositories.note_repository import NoteRepository
from app.services.note_service import NoteService

router = APIRouter(
    prefix="/campaigns/{campaign_id}/stations/{station_id}/notes",
    tags=["notes"],
)


def _service(db: Session = Depends(get_db)) -> NoteService:
    return NoteService(NoteRepository(db))


@router.get("", response_model=ListNotesResponse)
def list_station_notes(
    campaign_id: int,
    station_id: int,
    current_user: User = Depends(get_viewer_user),
    service: NoteService = Depends(_service),
) -> ListNotesResponse:
    return service.list_station_notes(campaign_id, station_id)


@router.post("", response_model=NoteCreateResponse, status_code=201)
def create_station_note(
    campaign_id: int,
    station_id: int,
    request: NoteCreate,
    current_user: User = Depends(get_edit_user),
    service: NoteService = Depends(_service),
) -> NoteCreateResponse:
    return service.create_station_note(request, campaign_id, station_id, current_user.username)


@router.patch("/{note_id}", response_model=NoteItem)
def update_station_note(
    campaign_id: int,
    station_id: int,
    note_id: int,
    request: NoteUpdate,
    current_user: User = Depends(get_edit_user),
    service: NoteService = Depends(_service),
) -> NoteItem:
    return service.update(note_id, request, current_user.username)


@router.delete("/{note_id}", status_code=204)
def delete_station_note(
    campaign_id: int,
    station_id: int,
    note_id: int,
    current_user: User = Depends(get_edit_user),
    service: NoteService = Depends(_service),
) -> None:
    service.delete(note_id, current_user.username)
