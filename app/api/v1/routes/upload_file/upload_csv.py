# type: ignore
import logging
import time
from datetime import datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.formparsers import MultiPartParser

from app.api.dependencies.auth import get_edit_user, get_tapis_token_header_optional
from app.api.v1.schemas.error import Error
from app.api.v1.schemas.upload import (
    UploadAudit,
    UploadCkanSync,
    UploadFileCsvResponse,
    UploadPostProcessing,
)
from app.api.v1.schemas.user import User
from app.core.config import Settings, get_settings
from app.db.models.upload_file_event import UploadFileEvent
from app.db.repositories.campaign_repository import CampaignRepository
from app.db.repositories.metadata_schema_repository import MetadataSchemaRepository
from app.db.repositories.sensor_repository import SensorRepository
from app.db.repositories.station_repository import StationRepository
from app.db.session import SessionLocal, get_db
from app.services.campaign_service import CampaignService
from app.services.ckan_publish import ensure_station_dataset, sync_sensor_resources
from app.services.ckan_service import get_ckan_service
from app.services.station_service import StationService
from app.utils.upload_csv import (
    process_measurements_file,
    process_sensors_file,
    update_sensor_statistics,
)

# Constants
MultiPartParser.spool_max_size = 500 * 1024 * 1024
BATCH_SIZE = 10000
DEFAULT_VARIABLE_NAME = "No BestGuess Formula"

router = APIRouter(prefix="/uploadfile_csv", tags=["uploadfile_csv"])
logger = logging.getLogger(__name__)


def is_measurement_batch_too_large_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "number of parameters must be between 0 and 65535" in message
        or "too many parameters" in message
    )


def create_upload_event(
    session: Session,
    campaign_id: int,
    station_id: int,
    upload_session_id: str | None,
    chunk_index: int | None,
    total_chunks: int | None,
) -> UploadFileEvent:
    """Create and return a new upload file event with session metadata."""
    upload_event = UploadFileEvent(
        time=datetime.now(),
        upload_session_id=upload_session_id,
        campaign_id=campaign_id,
        station_id=station_id,
        chunk_index=chunk_index,
        total_chunks=total_chunks,
    )
    session.add(upload_event)
    session.commit()
    return upload_event


def get_session_receipts(
    session: Session,
    campaign_id: int,
    station_id: int,
    upload_session_id: str,
) -> list[UploadFileEvent]:
    """Return all successful receipts for an upload session, newest first."""
    return (
        session.query(UploadFileEvent)
        .filter(
            UploadFileEvent.upload_session_id == upload_session_id,
            UploadFileEvent.campaign_id == campaign_id,
            UploadFileEvent.station_id == station_id,
        )
        .order_by(UploadFileEvent.id.desc())
        .all()
    )


def successful_receipt_chunk_indexes(
    session: Session,
    campaign_id: int,
    station_id: int,
    upload_session_id: str,
) -> set[int]:
    """Distinct chunk indexes with successful (measurement-counted) receipts."""
    receipts = get_session_receipts(session, campaign_id, station_id, upload_session_id)
    return {
        r.chunk_index
        for r in receipts
        if r.chunk_index is not None and r.measurement_values_inserted is not None
    }


def find_finalized_receipt(
    session: Session,
    campaign_id: int,
    station_id: int,
    upload_session_id: str,
) -> UploadFileEvent | None:
    """Return the finalized receipt of an upload session, if any."""
    return (
        session.query(UploadFileEvent)
        .filter(
            UploadFileEvent.upload_session_id == upload_session_id,
            UploadFileEvent.campaign_id == campaign_id,
            UploadFileEvent.station_id == station_id,
            UploadFileEvent.finalized.is_(True),
        )
        .first()
    )


def run_ckan_sync_upload(
    *,
    settings: Settings,
    tapis_token: str,
    campaign_id: int,
    station_id: int,
    sensor_ids: list[int],
    upload_session_id: str | None,
    upload_event_id: int,
) -> None:
    """Deferred CKAN dataset/resource sync for a finalized upload.

    Runs after the HTTP response is sent using its own database session so the
    request session lifecycle does not matter. The Tapis token is passed
    in-memory only and never persisted or logged.
    """
    db = SessionLocal()
    try:
        station_service = StationService(StationRepository(db))
        campaign_service = CampaignService(CampaignRepository(db))
        campaign = campaign_service.get_campaign_with_summary(campaign_id)
        station = station_service.get_station(station_id)
        if not (campaign and station and sensor_ids):
            logger.warning(
                "upload_csv_ckan_skipped extra=%s",
                {
                    "upload_event_id": upload_event_id,
                    "reason": "missing campaign/station/sensors",
                },
            )
            return
        owner_org = (
            campaign.allocation or settings.CKAN_ORGANIZATION or ""
        ).strip() or None
        if not owner_org:
            logger.warning(
                "upload_csv_ckan_skipped extra=%s",
                {"upload_event_id": upload_event_id, "reason": "no owner org"},
            )
            return
        metadata_repo = MetadataSchemaRepository(db)
        station_schema = metadata_repo.list_schema(scope="station", active_only=True)
        campaign_schema = metadata_repo.list_schema(scope="campaign", active_only=True)
        sensor_schema = metadata_repo.list_schema(scope="sensor", active_only=True)
        ckan_client = get_ckan_service()
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
        ckan_warnings = list(dataset_errors)
        sensor_repo = SensorRepository(db)
        sensors = sensor_repo.get_sensors_by_ids(sensor_ids)
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
        ckan_warnings.extend(resource_errors)
        for message in ckan_warnings:
            logger.warning(
                "upload_csv_ckan_warning extra=%s",
                {
                    "upload_event_id": upload_event_id,
                    "upload_session_id": upload_session_id,
                    "station_id": station_id,
                    "message": message,
                },
            )
    except Exception:
        logger.exception(
            "upload_csv_ckan_background_error extra=%s",
            {
                "upload_event_id": upload_event_id,
                "upload_session_id": upload_session_id,
            },
        )
    finally:
        db.close()


def schedule_ckan_sync(
    background_tasks: BackgroundTasks,
    *,
    tapis_token: str | None,
    campaign_id: int,
    station_id: int,
    sensor_ids: list[int],
    upload_session_id: str | None,
    upload_event_id: int,
) -> tuple[str, str | None]:
    """Schedule deferred CKAN sync; returns (status, message)."""
    if not tapis_token:
        logger.info(
            "upload_csv_ckan_skipped extra=%s",
            {"upload_event_id": upload_event_id, "reason": "no tapis token"},
        )
        return "missing_tapis_token", "CKAN sync skipped: no Tapis token provided."
    settings = get_settings()
    ckan_client = get_ckan_service()
    if not (ckan_client and settings.CKAN_URL):
        logger.info(
            "upload_csv_ckan_skipped extra=%s",
            {"upload_event_id": upload_event_id, "reason": "CKAN not configured"},
        )
        return "ckan_disabled", "CKAN sync skipped: integration not configured."
    background_tasks.add_task(
        run_ckan_sync_upload,
        settings=settings,
        tapis_token=tapis_token,
        campaign_id=campaign_id,
        station_id=station_id,
        sensor_ids=sensor_ids,
        upload_session_id=upload_session_id,
        upload_event_id=upload_event_id,
    )
    return "scheduled", None


@router.post(
    "/campaign/{campaign_id}/station/{station_id}/sensor",
    response_model=UploadFileCsvResponse,
    response_model_exclude_none=True,
)
def post_sensor_and_measurement(
    campaign_id: int,
    station_id: int,
    upload_file_sensors: Annotated[UploadFile, File(description="File with sensors.")],
    upload_file_measurements: Annotated[
        UploadFile, File(description="File with measurements.")
    ],
    background_tasks: BackgroundTasks,
    upload_session_id: Annotated[
        str | None,
        Form(
            description="Optional client-generated upload session id for chunked uploads."
        ),
    ] = None,
    finalize_upload: Annotated[
        bool,
        Form(
            description="True when this is the final chunk (default True for legacy single-request uploads)."
        ),
    ] = True,
    chunk_index: Annotated[
        int | None,
        Form(
            description="Zero-based chunk index of this request within the upload session."
        ),
    ] = None,
    total_chunks: Annotated[
        int | None, Form(description="Total number of chunks in the upload session.")
    ] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_edit_user),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
) -> UploadFileCsvResponse:
    """Process sensor and measurement files and store data in the database.

    Chunked uploads share a client-generated ``upload_session_id``. The
    measurements are inserted for every chunk; expensive post-processing
    (sensor statistics, station geometry, CKAN sync) runs only once when the
    upload session is verified complete.
    """
    start_time = time.time()
    sensor_repository = SensorRepository(db)
    station_service = StationService(StationRepository(db))

    # Create upload event with session metadata
    upload_event = create_upload_event(
        db,
        campaign_id=campaign_id,
        station_id=station_id,
        upload_session_id=upload_session_id,
        chunk_index=chunk_index,
        total_chunks=total_chunks,
    )
    upload_event_id = upload_event.id
    logger.info(
        "upload_csv_start extra=%s",
        {
            "campaign_id": campaign_id,
            "station_id": station_id,
            "upload_event_id": upload_event_id,
            "upload_session_id": upload_session_id,
            "finalize_upload": finalize_upload,
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
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
                "upload_event_id": upload_event_id,
                "sensors_filename": upload_file_sensors.filename,
            },
        )
        alias_to_sensorid_map = process_sensors_file(
            upload_file_sensors, station_id, upload_event_id, db
        )
        upload_file_sensors.file.close()
        logger.info(
            "upload_csv_process_sensors_done extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event_id,
                "sensor_alias_count": len(alias_to_sensorid_map),
                "sensor_aliases": sorted(alias_to_sensorid_map.keys()),
            },
        )

        logger.info(
            "upload_csv_process_measurements_start extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event_id,
                "measurements_filename": upload_file_measurements.filename,
            },
        )
        station = station_service.get_station(station_id)
        station_timezone = getattr(station, "timezone", None)
        if not isinstance(station_timezone, str) or not station_timezone:
            station_timezone = "UTC"
            logger.warning(
                "upload_csv_station_timezone_missing extra=%s",
                {
                    "campaign_id": campaign_id,
                    "station_id": station_id,
                    "upload_event_id": upload_event_id,
                    "fallback": station_timezone,
                },
            )
        measurements_result = process_measurements_file(
            upload_file_measurements,
            station_id,
            alias_to_sensorid_map,
            upload_event_id,
            db,
            station_timezone=station_timezone,
        )
        upload_file_measurements.file.close()
        logger.info(
            "upload_csv_process_measurements_done extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event_id,
                "rows_read": measurements_result.rows_read,
                "values_attempted": measurements_result.values_attempted,
                "values_inserted": measurements_result.values_inserted,
                "values_skipped_duplicate": measurements_result.values_skipped_duplicate,
                "error_count": len(measurements_result.errors),
                "errors": measurements_result.errors,
            },
        )

        # Persist the per-chunk audit receipt before finalization checks so
        # session completeness can be verified from the database.
        upload_event.measurement_rows_read = measurements_result.rows_read
        upload_event.measurement_values_attempted = measurements_result.values_attempted
        upload_event.measurement_values_inserted = measurements_result.values_inserted
        upload_event.measurement_values_skipped_duplicate = (
            measurements_result.values_skipped_duplicate
        )
        db.commit()

        is_chunked = bool(upload_session_id)
        is_final_chunk = (
            finalize_upload
            and chunk_index is not None
            and total_chunks is not None
            and chunk_index == total_chunks - 1
        )

        finalized = False
        post_processing_status = "not_finalized"
        statistics_refreshed = False
        station_geometry_refreshed = False
        ckan_sync_status = "not_finalized"
        ckan_sync_message: str | None = None
        finalization_errors: list[str] = []

        if not is_chunked:
            # Legacy single-request upload: no session tracking, always finalize.
            finalized = True
            post_processing_status = "completed"
        elif is_final_chunk:
            already_finalized = find_finalized_receipt(
                db, campaign_id, station_id, upload_session_id
            )
            if already_finalized:
                finalized = True
                post_processing_status = "already_finalized"
                ckan_sync_status = "already_finalized"
                ckan_sync_message = (
                    "Upload session already finalized; post-processing skipped."
                )
            else:
                successful_indexes = successful_receipt_chunk_indexes(
                    db, campaign_id, station_id, upload_session_id
                )
                expected_indexes = set(range(total_chunks))
                missing_indexes = sorted(expected_indexes - successful_indexes)
                if missing_indexes:
                    finalized = False
                    post_processing_status = "skipped_incomplete_upload"
                    ckan_sync_status = "skipped_incomplete_upload"
                    ckan_sync_message = (
                        "Upload not finalized: missing successful chunk(s) "
                        f"{missing_indexes}. No post-processing was run."
                    )
                    finalization_errors.append(ckan_sync_message)
                else:
                    finalized = True
                    post_processing_status = "completed"
        else:
            # Non-final chunk of a chunked upload.
            finalized = False
            post_processing_status = "not_finalized"
            ckan_sync_status = "not_finalized"
            ckan_sync_message = "Chunk stored; awaiting remaining chunks."

        if finalized and post_processing_status == "completed":
            logger.info(
                "upload_csv_update_sensor_statistics_start extra=%s",
                {
                    "campaign_id": campaign_id,
                    "station_id": station_id,
                    "upload_event_id": upload_event_id,
                    "upload_session_id": upload_session_id,
                    "sensor_ids": sorted(alias_to_sensorid_map.values()),
                },
            )
            update_sensor_statistics(sensor_repository, alias_to_sensorid_map)
            statistics_refreshed = True
            logger.info(
                "upload_csv_update_sensor_statistics_done extra=%s",
                {
                    "campaign_id": campaign_id,
                    "station_id": station_id,
                    "upload_event_id": upload_event_id,
                },
            )

            logger.info(
                "upload_csv_refresh_geometry_start extra=%s",
                {
                    "campaign_id": campaign_id,
                    "station_id": station_id,
                    "upload_event_id": upload_event_id,
                },
            )
            station_service.refresh_geometry(station_id)
            station_geometry_refreshed = True
            logger.info(
                "upload_csv_refresh_geometry_done extra=%s",
                {
                    "campaign_id": campaign_id,
                    "station_id": station_id,
                    "upload_event_id": upload_event_id,
                },
            )

            ckan_sync_status, ckan_sync_message = schedule_ckan_sync(
                background_tasks,
                tapis_token=tapis_token,
                campaign_id=campaign_id,
                station_id=station_id,
                sensor_ids=list(alias_to_sensorid_map.values()),
                upload_session_id=upload_session_id,
                upload_event_id=upload_event_id,
            )

            upload_event.finalized = True
            upload_event.finalized_at = datetime.now()
            db.commit()

        data_processing_time = round(time.time() - start_time, 1)
        response = UploadFileCsvResponse(
            upload_event_id=upload_event_id,
            upload_session_id=upload_session_id,
            finalized=finalized,
            chunk_index=chunk_index,
            total_chunks=total_chunks,
            audit=UploadAudit(
                measurement_rows_read=measurements_result.rows_read,
                measurement_values_attempted=measurements_result.values_attempted,
                measurement_values_inserted=measurements_result.values_inserted,
                measurement_values_skipped_duplicate=measurements_result.values_skipped_duplicate,
                sensor_alias_count=len(alias_to_sensorid_map),
                row_errors=measurements_result.errors,
            ),
            post_processing=UploadPostProcessing(
                status=post_processing_status,
                statistics_refreshed=statistics_refreshed,
                station_geometry_refreshed=station_geometry_refreshed,
            ),
            ckan_sync=UploadCkanSync(
                status=ckan_sync_status,
                message=ckan_sync_message,
            ),
            uploaded_file_sensors_stored_in_memory=upload_file_sensors._in_memory,
            uploaded_file_measurements_stored_in_memory=upload_file_measurements._in_memory,
            total_sensors_processed=len(alias_to_sensorid_map),
            total_measurements_added_to_database=measurements_result.values_inserted,
            data_processing_time=f"{data_processing_time} seconds.",
            errors=[
                Error(message=error)
                for error in measurements_result.errors + finalization_errors
            ],
            ckan_warnings=None,
        )

        logger.info(
            "upload_csv_done extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event_id,
                "upload_session_id": upload_session_id,
                "finalized": finalized,
                "total_sensors": len(alias_to_sensorid_map),
                "total_measurements": measurements_result.values_inserted,
                "processing_seconds": data_processing_time,
                "error_count": len(measurements_result.errors),
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
                "upload_event_id": upload_event_id,
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
                "upload_event_id": upload_event_id,
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
                    f"upload_event_id={upload_event_id}"
                ),
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=f"Internal upload error. See server logs. upload_event_id={upload_event_id}",
        ) from exc
    except Exception:
        db.rollback()
        logger.exception(
            "upload_csv_unhandled_exception extra=%s",
            {
                "campaign_id": campaign_id,
                "station_id": station_id,
                "upload_event_id": upload_event_id,
                "sensors_filename": upload_file_sensors.filename,
                "measurements_filename": upload_file_measurements.filename,
            },
        )
        raise HTTPException(
            status_code=500,
            detail=f"Internal upload error. See server logs. upload_event_id={upload_event_id}",
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
