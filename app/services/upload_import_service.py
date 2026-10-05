"""Durable state transitions and single-worker processing for async imports."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models.sensor import Sensor
from app.db.models.upload_file_event import UploadFileEvent
from app.db.models.upload_import import UploadImport, UploadImportChunk
from app.db.models.upload_import_backfill import UploadImportBackfill
from app.db.repositories.sensor_repository import SensorRepository
from app.db.repositories.station_repository import StationRepository
from app.services.station_service import StationService
from app.utils.bulk_upload_csv import BulkMeasurementsProcessingResult, process_measurements_file_bulk
from app.utils.upload_csv import process_sensors_file, update_sensor_statistics
from app.services.upload_import_storage import import_file_path
from app.services.upload_import_backfill_service import (
    ensure_backfill_state,
    materialize_and_validate,
    merge_backfill,
    stage_backfill_chunk,
    _station_lock,
)


TERMINAL_IMPORT_STATUSES = {"completed", "failed"}


class UploadImportLeaseLost(RuntimeError):
    """Raised when a worker no longer owns an import lease."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_import(
    db: Session,
    *,
    import_id: str,
    campaign_id: int,
    station_id: int,
    owner_username: str,
    total_chunks: int,
    total_bytes: int,
    storage_key: str,
    ingestion_mode: str = "standard",
) -> UploadImport:
    now = utcnow()
    record = UploadImport(
        id=import_id,
        campaign_id=campaign_id,
        station_id=station_id,
        owner_username=owner_username,
        total_chunks=total_chunks,
        total_bytes=total_bytes,
        status="created",
        ingestion_mode=ingestion_mode,
        storage_key=storage_key,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_import_for_owner(
    db: Session, import_id: str, owner_username: str
) -> UploadImport | None:
    record = db.query(UploadImport).filter(UploadImport.id == import_id).first()
    if record is None or record.owner_username != owner_username:
        return None
    return record


def import_progress(db: Session, record: UploadImport) -> tuple[int, int]:
    received = (
        db.query(func.count(UploadImportChunk.id))
        .filter(UploadImportChunk.import_id == record.id)
        .scalar()
    ) or 0
    processed = (
        db.query(func.count(UploadImportChunk.id))
        .filter(
            UploadImportChunk.import_id == record.id,
            UploadImportChunk.processed.is_(True),
        )
        .scalar()
    ) or 0
    return int(received), int(processed)


def claim_import(
    db: Session, settings: Settings, import_id: str | None = None
) -> tuple[UploadImport, str] | None:
    now = utcnow()
    eligible = or_(
        UploadImport.status == "queued",
        and_(
            UploadImport.status == "processing",
            UploadImport.lease_expires_at.is_not(None),
            UploadImport.lease_expires_at <= now,
        ),
    )
    query = db.query(UploadImport).filter(eligible)
    if not settings.BULK_BACKFILL_ENABLED:
        query = query.filter(UploadImport.ingestion_mode != "backfill")
    if import_id:
        query = query.filter(UploadImport.id == import_id)
    record = query.order_by(UploadImport.created_at).with_for_update(skip_locked=True).first()
    if record is None:
        return None
    token = str(uuid4())
    record.status = "processing"
    record.worker_token = token
    record.lease_expires_at = now + timedelta(seconds=settings.BULK_IMPORT_WORKER_LEASE_SECONDS)
    record.attempts += 1
    record.updated_at = now
    db.commit()
    return record, token


def heartbeat(db: Session, settings: Settings, import_id: str, worker_token: str) -> None:
    now = utcnow()
    record = (
        db.query(UploadImport)
        .filter(
            UploadImport.id == import_id,
            UploadImport.status == "processing",
            UploadImport.worker_token == worker_token,
        )
        .first()
    )
    if record is None:
        raise UploadImportLeaseLost(f"Worker lease lost for import {import_id}")
    record.lease_expires_at = now + timedelta(seconds=settings.BULK_IMPORT_WORKER_LEASE_SECONDS)
    record.updated_at = now
    db.commit()


def _create_or_get_event(db: Session, record: UploadImport, chunk: UploadImportChunk) -> UploadFileEvent:
    if chunk.upload_event_id is not None:
        event = db.query(UploadFileEvent).filter(UploadFileEvent.id == chunk.upload_event_id).first()
        if event is not None:
            return event
    event = UploadFileEvent(
        time=datetime.now(),
        upload_session_id=record.id,
        campaign_id=record.campaign_id,
        station_id=record.station_id,
        chunk_index=chunk.chunk_index,
        total_chunks=record.total_chunks,
        ingestion_mode=("bulk_backfill" if record.ingestion_mode == "backfill" else "bulk_async"),
    )
    db.add(event)
    db.flush()
    chunk.upload_event_id = event.id
    db.commit()
    return event


def _sensor_mapping_from_file(
    sensors_path: Path,
    *,
    station_id: int,
    event_id: int,
    db: Session,
) -> dict[str, int]:
    with sensors_path.open("rb") as handle:
        return process_sensors_file(
            UploadFile(file=handle, filename="sensors.csv"),
            station_id,
            event_id,
            db,
        )


def process_claimed_import(
    db: Session,
    settings: Settings,
    record: UploadImport,
    worker_token: str,
) -> tuple[UploadImport, dict[str, int]]:
    if record.status != "processing" or record.worker_token != worker_token:
        raise UploadImportLeaseLost(f"Import {record.id} is not owned by this worker")
    if record.ingestion_mode == "backfill" and not settings.BULK_BACKFILL_ENABLED:
        raise ValueError("Bulk backfill is not enabled")

    sensors_key = record.sensors_storage_key
    if not sensors_key:
        raise ValueError("Import has no sensor metadata")
    sensors_path = import_file_path(settings, record.storage_key, sensors_key)
    backfill_state: UploadImportBackfill | None = None
    if record.ingestion_mode == "backfill":
        backfill_state = ensure_backfill_state(db, record)
    chunks = (
        db.query(UploadImportChunk)
        .filter(UploadImportChunk.import_id == record.id)
        .order_by(UploadImportChunk.chunk_index)
        .all()
    )
    if len(chunks) != record.total_chunks:
        raise ValueError("Import manifest is incomplete")

    alias_to_sensorid = dict(record.sensor_mapping or {})
    for chunk in chunks:
        heartbeat(db, settings, record.id, worker_token)
        if chunk.processed:
            if not alias_to_sensorid and chunk.upload_event_id:
                alias_to_sensorid = {
                    alias: sensor_id
                    for alias, sensor_id in db.query(Sensor.alias, Sensor.sensorid)
                    .filter(Sensor.stationid == record.station_id, Sensor.alias.is_not(None))
                    .all()
                    if alias is not None
                }
            continue

        event = _create_or_get_event(db, record, chunk)
        alias_to_sensorid = _sensor_mapping_from_file(
            sensors_path,
            station_id=record.station_id,
            event_id=event.id,
            db=db,
        )
        record.sensor_mapping = alias_to_sensorid
        measurement_path = import_file_path(settings, record.storage_key, chunk.storage_key)
        station_timezone = (
            getattr(StationRepository(db).get_station(record.station_id), "timezone", None)
            or "UTC"
        )
        if backfill_state is not None:
            rows_read, values_attempted = stage_backfill_chunk(
                db,
                settings,
                record,
                backfill_state,
                chunk,
                event,
                measurement_path,
                alias_to_sensorid,
                station_timezone,
            )
            result = BulkMeasurementsProcessingResult(
                rows_read=rows_read,
                values_attempted=values_attempted,
                values_inserted=0,
            )
        else:
            with measurement_path.open("rb") as handle:
                result = process_measurements_file_bulk(
                    UploadFile(file=handle, filename=f"chunk-{chunk.chunk_index}.csv"),
                    record.station_id,
                    alias_to_sensorid,
                    event.id,
                    db,
                    station_timezone=station_timezone,
                    staging_batch_size=settings.BULK_IMPORT_STAGING_BATCH_SIZE,
                    station_lock_callback=lambda: _station_lock(db, record.station_id),
                )
        event.measurement_rows_read = result.rows_read
        event.measurement_values_attempted = result.values_attempted
        event.measurement_values_inserted = result.values_inserted
        event.measurement_values_skipped_duplicate = result.values_skipped_duplicate
        chunk.rows_read = result.rows_read
        chunk.values_attempted = result.values_attempted
        chunk.values_inserted = result.values_inserted
        chunk.processed = True
        chunk.processed_at = utcnow()
        record.rows_read += result.rows_read
        record.values_attempted += result.values_attempted
        record.values_inserted += result.values_inserted
        record.updated_at = utcnow()
        db.commit()

    heartbeat(db, settings, record.id, worker_token)
    if not alias_to_sensorid:
        raise ValueError("Import produced no sensor mapping")
    if backfill_state is not None and backfill_state.phase != "merged":
        if backfill_state.phase in {"staging", "materializing", "validating"}:
            materialize_and_validate(db, record, backfill_state)
        merge_backfill(db, settings, record, backfill_state)
    if backfill_state is not None:
        record.values_inserted = backfill_state.merged_values
    record.status = "data_loaded"
    record.last_error = None
    record.data_loaded_at = utcnow()
    record.lease_expires_at = None
    record.worker_token = None
    record.updated_at = utcnow()
    db.commit()
    return record, alias_to_sensorid


def claim_post_processing(
    db: Session, settings: Settings, import_id: str | None = None
) -> tuple[UploadImport, str] | None:
    """Claim a data-loaded import for its independent statistics refresh."""
    now = utcnow()
    eligible = and_(
        UploadImport.status == "data_loaded",
        or_(
            UploadImport.post_processing_status == "pending",
            and_(
                UploadImport.post_processing_status == "failed",
                UploadImport.post_processing_attempts < settings.BULK_IMPORT_MAX_ATTEMPTS,
            ),
            and_(
                UploadImport.post_processing_status == "processing",
                UploadImport.post_processing_attempts < settings.BULK_IMPORT_MAX_ATTEMPTS,
                UploadImport.post_processing_lease_expires_at.is_not(None),
                UploadImport.post_processing_lease_expires_at <= now,
            ),
        ),
    )
    query = db.query(UploadImport).filter(eligible)
    if import_id:
        query = query.filter(UploadImport.id == import_id)
    record = query.order_by(
        UploadImport.data_loaded_at, UploadImport.created_at
    ).with_for_update(skip_locked=True).first()
    if record is None:
        return None
    token = str(uuid4())
    record.post_processing_status = "processing"
    record.post_processing_token = token
    record.post_processing_lease_expires_at = now + timedelta(
        seconds=settings.BULK_IMPORT_WORKER_LEASE_SECONDS
    )
    record.post_processing_attempts += 1
    record.post_processing_started_at = now
    record.post_processing_error = None
    if record.post_processing_stage is None:
        record.post_processing_stage = "statistics"
    record.updated_at = now
    db.commit()
    return record, token


def heartbeat_post_processing(
    db: Session, settings: Settings, import_id: str, post_processing_token: str
) -> None:
    now = utcnow()
    record = (
        db.query(UploadImport)
        .filter(
            UploadImport.id == import_id,
            UploadImport.status == "data_loaded",
            UploadImport.post_processing_status == "processing",
            UploadImport.post_processing_token == post_processing_token,
        )
        .first()
    )
    if record is None:
        raise UploadImportLeaseLost(f"Post-processing lease lost for import {import_id}")
    record.post_processing_lease_expires_at = now + timedelta(
        seconds=settings.BULK_IMPORT_WORKER_LEASE_SECONDS
    )
    record.updated_at = now
    db.commit()


def post_process_claimed_import(
    db: Session,
    settings: Settings,
    record: UploadImport,
    post_processing_token: str,
) -> UploadImport:
    """Run one retryable statistics/geometry stage after ingestion completes."""
    import_id = record.id
    station_id = record.station_id
    stage = record.post_processing_stage or "statistics"
    if (
        record.status != "data_loaded"
        or record.post_processing_status != "processing"
        or record.post_processing_token != post_processing_token
    ):
        raise UploadImportLeaseLost(
            f"Post-processing lease for import {import_id} is not owned by this worker"
        )

    alias_to_sensorid = dict(record.sensor_mapping or {})
    if not alias_to_sensorid:
        raise ValueError("Import produced no sensor mapping")

    if stage == "statistics":
        heartbeat_post_processing(db, settings, import_id, post_processing_token)
        update_sensor_statistics(
            SensorRepository(db),
            alias_to_sensorid,
            heartbeat_callback=lambda: heartbeat_post_processing(
                db, settings, import_id, post_processing_token
            ),
        )
        advanced = (
            db.query(UploadImport)
            .filter(
                UploadImport.id == import_id,
                UploadImport.status == "data_loaded",
                UploadImport.post_processing_status == "processing",
                UploadImport.post_processing_token == post_processing_token,
            )
            .update(
                {
                    UploadImport.post_processing_stage: "geometry",
                    UploadImport.updated_at: utcnow(),
                },
                synchronize_session=False,
            )
        )
        if advanced != 1:
            db.rollback()
            raise UploadImportLeaseLost(
                f"Post-processing lease for import {import_id} was lost after statistics"
            )
        db.commit()
        stage = "geometry"

    if stage != "geometry":
        raise ValueError(f"Unknown post-processing stage: {stage}")

    heartbeat_post_processing(db, settings, import_id, post_processing_token)
    StationService(StationRepository(db)).refresh_geometry(
        station_id,
        statement_timeout_ms=settings.BULK_IMPORT_GEOMETRY_STATEMENT_TIMEOUT_MS,
    )
    completed_at = utcnow()
    updated = (
        db.query(UploadImport)
        .filter(
            UploadImport.id == import_id,
            UploadImport.status == "data_loaded",
            UploadImport.post_processing_status == "processing",
            UploadImport.post_processing_token == post_processing_token,
        )
        .update(
            {
                UploadImport.post_processing_status: "completed",
                UploadImport.post_processing_stage: None,
                UploadImport.post_processing_error: None,
                UploadImport.post_processing_completed_at: completed_at,
                UploadImport.post_processing_lease_expires_at: None,
                UploadImport.post_processing_token: None,
                UploadImport.status: "completed",
                UploadImport.completed_at: completed_at,
                UploadImport.updated_at: completed_at,
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        db.rollback()
        raise UploadImportLeaseLost(
            f"Post-processing lease for import {import_id} was lost before completion"
        )
    db.commit()
    completed_record = db.query(UploadImport).filter(UploadImport.id == import_id).one()
    return completed_record


def mark_import_failure(
    db: Session,
    settings: Settings,
    import_id: str,
    worker_token: str,
    error: Exception,
) -> bool:
    record = (
        db.query(UploadImport)
        .filter(UploadImport.id == import_id, UploadImport.worker_token == worker_token)
        .first()
    )
    if record is None:
        return False
    terminal = record.attempts >= settings.BULK_IMPORT_MAX_ATTEMPTS
    record.status = "failed" if terminal else "queued"
    # Keep SQL, local paths, and CSV content out of the user-visible status.
    record.last_error = f"{type(error).__name__}: import processing failed"
    record.worker_token = None
    record.lease_expires_at = None
    record.updated_at = utcnow()
    db.commit()
    return terminal


def mark_post_processing_failure(
    db: Session,
    settings: Settings,
    import_id: str,
    post_processing_token: str,
    error: Exception,
) -> bool:
    record = (
        db.query(UploadImport)
        .filter(
            UploadImport.id == import_id,
            UploadImport.status == "data_loaded",
            UploadImport.post_processing_status == "processing",
            UploadImport.post_processing_token == post_processing_token,
        )
        .with_for_update()
        .first()
    )
    if record is None:
        return False
    terminal = record.post_processing_attempts >= settings.BULK_IMPORT_MAX_ATTEMPTS
    record.post_processing_status = "failed" if terminal else "pending"
    record.post_processing_error = (
        f"{type(error).__name__}: post-processing failed"
    )
    record.post_processing_token = None
    record.post_processing_lease_expires_at = None
    record.updated_at = utcnow()
    db.commit()
    return terminal
