# type: ignore
import logging
import time
from datetime import datetime
from typing import Annotated, Dict, Any, List

from starlette.formparsers import MultiPartParser
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_edit_user, get_tapis_token_header_optional
from app.api.v1.schemas.user import User
from app.api.v1.schemas.error import Error
from app.db.models.upload_file_event import UploadFileEvent
from app.db.session import SessionLocal, get_db
from app.db.repositories.campaign_repository import CampaignRepository
from app.db.repositories.sensor_repository import SensorRepository
from app.db.repositories.measurement_repository import MeasurementRepository
from app.db.repositories.station_repository import StationRepository
from app.services.campaign_service import CampaignService
from app.services.ckan_publish import ensure_station_dataset, sync_sensor_resources
from app.services.ckan_service import get_ckan_service
from app.services.station_service import StationService
from app.core.config import get_settings
from app.utils.upload_csv import process_sensors_file, process_measurements_file, update_sensor_statistics


# Constants
MultiPartParser.spool_max_size = 500 * 1024 * 1024
BATCH_SIZE = 10000
DEFAULT_VARIABLE_NAME = 'No BestGuess Formula'

router = APIRouter(prefix="/uploadfile_csv", tags=["uploadfile_csv"])
logger = logging.getLogger(__name__)

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
    current_user: User = Depends(get_edit_user),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
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

    ckan_sync_messages: list[str] = []
    if tapis_token:
        settings = get_settings()
        ckan_client = get_ckan_service()
        if ckan_client and settings.CKAN_URL:
            campaign_service = CampaignService(CampaignRepository(db))
            station_service = StationService(StationRepository(db))
            campaign = campaign_service.get_campaign_with_summary(campaign_id)
            station = station_service.get_station(station_id)
            if campaign and station and alias_to_sensorid_map:
                owner_org = (campaign.allocation or settings.CKAN_ORGANIZATION or "").strip() or None
                if owner_org:
                    dataset, dataset_id, dataset_errors = ensure_station_dataset(
                        settings=settings,
                        ckan_client=ckan_client,
                        tapis_token=tapis_token,
                        campaign=campaign,
                        station=station,
                        owner_org=owner_org,
                        private=True,
                    )
                    ckan_sync_messages.extend(dataset_errors)
                    sensors = sensor_repository.get_sensors_by_ids(list(alias_to_sensorid_map.values()))
                    resource_errors = sync_sensor_resources(
                        settings=settings,
                        ckan_client=ckan_client,
                        tapis_token=tapis_token,
                        campaign=campaign,
                        station=station,
                        dataset=dataset,
                        dataset_id=dataset_id,
                        sensors=sensors,
                    )
                    ckan_sync_messages.extend(resource_errors)
        else:
            logger.info("Skipping CKAN sensor sync for station %s: CKAN integration not configured.", station_id)
    else:
        logger.info("Skipping CKAN sensor sync for station %s: no Tapis token provided.", station_id)

    response.update({
        'Total sensors processed': len(alias_to_sensorid_map),
        'Total measurements added to database': total_measurements,
        'Data Processing time': f"{data_processing_time} seconds.",
        'errors': [Error(message=error) for error in errors]
    })
    if ckan_sync_messages:
        response['ckan_warnings'] = ckan_sync_messages

    return response
