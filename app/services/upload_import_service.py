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
from app.db.repositories.sensor_repository import SensorRepository
from app.db.repositories.station_repository import StationRepository
from app.services.station_service import StationService
from app.utils.bulk_upload_csv import process_measurements_file_bulk
from app.utils.upload_csv import process_sensors_file, update_sensor_statistics
from app.services.upload_import_storage import import_file_path


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
        ingestion_mode="bulk_async",
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
) -> UploadImport:
    if record.status != "processing" or record.worker_token != worker_token:
        raise UploadImportLeaseLost(f"Import {record.id} is not owned by this worker")

    sensors_key = record.sensors_storage_key
    if not sensors_key:
        raise ValueError("Import has no sensor metadata")
    sensors_path = import_file_path(settings, record.storage_key, sensors_key)
    chunks = (
        db.query(UploadImportChunk)
        .filter(UploadImportChunk.import_id == record.id)
        .order_by(UploadImportChunk.chunk_index)
        .all()
    )
    if len(chunks) != record.total_chunks:
        raise ValueError("Import manifest is incomplete")

    alias_to_sensorid: dict[str, int] = {}
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
        measurement_path = import_file_path(settings, record.storage_key, chunk.storage_key)
        with measurement_path.open("rb") as handle:
            result = process_measurements_file_bulk(
                UploadFile(file=handle, filename=f"chunk-{chunk.chunk_index}.csv"),
                record.station_id,
                alias_to_sensorid,
                event.id,
                db,
                station_timezone=(
                    getattr(StationRepository(db).get_station(record.station_id), "timezone", None)
                    or "UTC"
                ),
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
    update_sensor_statistics(SensorRepository(db), alias_to_sensorid)
    StationService(StationRepository(db)).refresh_geometry(record.station_id)
    current_record = db.query(UploadImport).filter(UploadImport.id == record.id).first()
    if (
        current_record is None
        or current_record.worker_token != worker_token
        or current_record.status != "processing"
    ):
        raise UploadImportLeaseLost(f"Import {worker_token} lost ownership before completion")
    current_record.status = "completed"
    current_record.last_error = None
    current_record.completed_at = utcnow()
    current_record.lease_expires_at = None
    current_record.worker_token = None
    current_record.updated_at = utcnow()
    db.commit()
    return current_record


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
