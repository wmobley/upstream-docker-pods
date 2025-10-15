# type: ignore
import time
from datetime import datetime
from typing import Annotated, Dict, Any, List

from starlette.formparsers import MultiPartParser
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.api.v1.schemas.user import User
from app.api.v1.schemas.error import Error
from app.db.models.upload_file_event import UploadFileEvent
from app.db.session import SessionLocal, get_db
from app.db.repositories.sensor_repository import SensorRepository
from app.db.repositories.measurement_repository import MeasurementRepository
from app.utils.upload_csv import process_sensors_file, process_measurements_file, update_sensor_statistics


# Constants
MultiPartParser.spool_max_size = 500 * 1024 * 1024
BATCH_SIZE = 10000
DEFAULT_VARIABLE_NAME = 'No BestGuess Formula'

router = APIRouter(prefix="/uploadfile_csv", tags=["uploadfile_csv"])

def create_upload_event(session: Session) -> UploadFileEvent:
    """Create and return a new upload file event."""
    upload_event = UploadFileEvent(time=datetime.now())
    session.add(upload_event)
    session.commit()
    return upload_event


@router.post("/campaign/{campaign_id}/station/{station_id}/sensor")
def post_sensor_and_measurement(
    campaign_id: int,
    station_id: int,
    upload_file_sensors: Annotated[UploadFile, File(description="File with sensors.")],
    upload_file_measurements: Annotated[UploadFile, File(description="File with measurements.")],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Process sensor and measurement files and store data in the database."""
    start_time = time.time()
    sensor_repository = SensorRepository(db)

    response = {
        'uploaded_file_sensors stored in memory': upload_file_sensors._in_memory,
        'uploaded_file_measurements stored in memory': upload_file_measurements._in_memory
    }

    # Create upload event
    upload_event = create_upload_event(db)

    # Process sensors file
    alias_to_sensorid_map = process_sensors_file(
            upload_file_sensors, station_id, upload_event.id, db
        )
    upload_file_sensors.file.close()

    # Process measurements file
    total_measurements, errors = process_measurements_file(upload_file_measurements, station_id, alias_to_sensorid_map, upload_event.id, db)
    upload_file_measurements.file.close()
    data_processing_time = round(time.time() - start_time, 1)
    update_sensor_statistics(sensor_repository, alias_to_sensorid_map)

    response.update({
        'Total sensors processed': len(alias_to_sensorid_map),
        'Total measurements added to database': total_measurements,
        'Data Processing time': f"{data_processing_time} seconds.",
        'errors': [Error(message=error) for error in errors]
    })

    return response

