# type: ignore
import logging
import time
from datetime import datetime
from typing import Annotated, Dict, Any, List

from starlette.formparsers import MultiPartParser
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from app.api.dependencies.auth import get_edit_user, get_tapis_token_header_optional
from app.api.v1.schemas.user import User
from app.api.v1.schemas.error import Error
from app.db.models.upload_file_event import UploadFileEvent
from app.db.session import SessionLocal, get_db
from app.db.repositories.campaign_repository import CampaignRepository
from app.db.repositories.sensor_repository import SensorRepository
from app.db.repositories.measurement_repository import MeasurementRepository
from app.db.repositories.station_repository import StationRepository
from app.db.repositories.metadata_schema_repository import MetadataSchemaRepository
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


def is_measurement_batch_too_large_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "number of parameters must be between 0 and 65535" in message
        or "too many parameters" in message
    )

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
    station_service = StationService(StationRepository(db))

    response = {
        'uploaded_file_sensors stored in memory': upload_file_sensors._in_memory,
        'uploaded_file_measurements stored in memory': upload_file_measurements._in_memory
    }

    # Create upload event
    upload_event = create_upload_event(db)
    logger.info(
        "upload_csv_start extra=%s",
        {
            "campaign_id": campaign_id,
            "station_id": station_id,
            "upload_event_id": upload_event.id,
            "user": getattr(current_user, "username", None),
            "sensors_filename": upload_file_sensors.filename,
            "measurements_filename": upload_file_measurements.filename,
            "sensors_in_memory": upload_file_sensors._in_memory,
            "measurements_in_memory": upload_file_measurements._in_memory,
            "tapis_token_present": bool(tapis_token),
        },
    )

    try:
        logger.info(
            "upload_csv_process_sensors_start extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event.id,
                "sensors_filename": upload_file_sensors.filename,
            },
        )
        alias_to_sensorid_map = process_sensors_file(
            upload_file_sensors, station_id, upload_event.id, db
        )
        upload_file_sensors.file.close()
        logger.info(
            "upload_csv_process_sensors_done extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event.id,
                "sensor_alias_count": len(alias_to_sensorid_map),
                "sensor_aliases": sorted(alias_to_sensorid_map.keys()),
            },
        )

        logger.info(
            "upload_csv_process_measurements_start extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event.id,
                "measurements_filename": upload_file_measurements.filename,
            },
        )
        total_measurements, errors = process_measurements_file(
            upload_file_measurements, station_id, alias_to_sensorid_map, upload_event.id, db
        )
        upload_file_measurements.file.close()
        logger.info(
            "upload_csv_process_measurements_done extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event.id,
                "total_measurements": total_measurements,
                "error_count": len(errors),
                "errors": errors,
            },
        )

        logger.info(
            "upload_csv_update_sensor_statistics_start extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event.id,
                "sensor_ids": sorted(alias_to_sensorid_map.values()),
            },
        )
        update_sensor_statistics(sensor_repository, alias_to_sensorid_map)
        logger.info(
            "upload_csv_update_sensor_statistics_done extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event.id,
            },
        )

        logger.info(
            "upload_csv_refresh_geometry_start extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event.id,
            },
        )
        station_service.refresh_geometry(station_id)
        logger.info(
            "upload_csv_refresh_geometry_done extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event.id,
            },
        )

        ckan_sync_messages: list[str] = []
        if tapis_token:
            settings = get_settings()
            ckan_client = get_ckan_service()
            if ckan_client and settings.CKAN_URL:
                campaign_service = CampaignService(CampaignRepository(db))
                campaign = campaign_service.get_campaign_with_summary(campaign_id)
                station = station_service.get_station(station_id)
                if campaign and station and alias_to_sensorid_map:
                    owner_org = (campaign.allocation or settings.CKAN_ORGANIZATION or "").strip() or None
                    if owner_org:
                        metadata_repo = MetadataSchemaRepository(db)
                        station_schema = metadata_repo.list_schema(scope="station", active_only=True)
                        campaign_schema = metadata_repo.list_schema(scope="campaign", active_only=True)
                        sensor_schema = metadata_repo.list_schema(scope="sensor", active_only=True)
                        dataset, dataset_id, dataset_errors = ensure_station_dataset(
                            settings=settings,
                            ckan_client=ckan_client,
                            tapis_token=tapis_token,
                            campaign=campaign,
                            station=station,
                            owner_org=owner_org,
                            private=True,
                            station_metadata_schema=station_schema,
                            campaign_metadata_schema=campaign_schema,
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
                            sensor_metadata_schema=sensor_schema,
                        )
                        ckan_sync_messages.extend(resource_errors)
            else:
                logger.info("Skipping CKAN sensor sync for station %s: CKAN integration not configured.", station_id)
        else:
            logger.info("Skipping CKAN sensor sync for station %s: no Tapis token provided.", station_id)

        data_processing_time = round(time.time() - start_time, 1)
        response.update({
            'Total sensors processed': len(alias_to_sensorid_map),
            'Total measurements added to database': total_measurements,
            'Data Processing time': f"{data_processing_time} seconds.",
            'errors': [Error(message=error) for error in errors]
        })
        if ckan_sync_messages:
            response['ckan_warnings'] = ckan_sync_messages

        logger.info(
            "upload_csv_done extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event.id,
                "total_sensors": len(alias_to_sensorid_map),
                "total_measurements": total_measurements,
                "processing_seconds": data_processing_time,
                "error_count": len(errors),
            },
        )
        return response
    except HTTPException:
        db.rollback()
        logger.exception(
            "upload_csv_http_exception extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event.id,
                "sensors_filename": upload_file_sensors.filename,
                "measurements_filename": upload_file_measurements.filename,
            },
        )
        raise
    except OperationalError as exc:
        db.rollback()
        logger.exception(
            "upload_csv_operational_error extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event.id,
                "sensors_filename": upload_file_sensors.filename,
                "measurements_filename": upload_file_measurements.filename,
            },
        )
        if is_measurement_batch_too_large_error(exc):
            raise HTTPException(
                status_code=413,
                detail=(
                    "Upload is too large for a single database write batch. "
                    "Split the measurements into smaller uploads and retry. "
                    f"upload_event_id={upload_event.id}"
                ),
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=f"Internal upload error. See server logs. upload_event_id={upload_event.id}",
        ) from exc
    except Exception:
        db.rollback()
        logger.exception(
            "upload_csv_unhandled_exception extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event.id,
                "sensors_filename": upload_file_sensors.filename,
                "measurements_filename": upload_file_measurements.filename,
            },
        )
        raise HTTPException(
            status_code=500,
            detail=f"Internal upload error. See server logs. upload_event_id={upload_event.id}",
        )
    finally:
        try:
            upload_file_sensors.file.close()
        except Exception:
            pass
        try:
            upload_file_measurements.file.close()
        except Exception:
            pass
