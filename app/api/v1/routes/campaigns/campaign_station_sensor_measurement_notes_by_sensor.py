from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_viewer_user
from app.api.v1.schemas.note import ListMeasurementNotesResponse
from app.api.v1.schemas.user import User
from app.db.repositories.note_repository import NoteRepository
from app.db.session import get_db
from app.services.note_service import NoteService

router = APIRouter(
    prefix="/campaigns/{campaign_id}/stations/{station_id}/sensors/{sensor_id}/measurement-notes",
    tags=["notes"],
)


def _service(db: Session = Depends(get_db)) -> NoteService:
    return NoteService(NoteRepository(db))


@router.get("", response_model=ListMeasurementNotesResponse)
def list_measurement_notes_by_sensor(
    campaign_id: int,
    station_id: int,
    sensor_id: int,
    current_user: User = Depends(get_viewer_user),
    service: NoteService = Depends(_service),
) -> ListMeasurementNotesResponse:
    return service.list_measurement_notes_by_sensor(campaign_id, station_id, sensor_id)
