"""Opt-in durable async bulk-import control plane."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_edit_user
from app.api.v1.schemas.upload_import import (
    UploadImportChunkMetadata,
    UploadImportChunkResponse,
    UploadImportCreate,
    UploadImportFinalizeResponse,
    UploadImportStatusResponse,
    FinalizeImportStatus,
    ImportStatus,
    PostProcessingStage,
    PostProcessingStatus,
)
from app.api.v1.schemas.user import User
from app.core.config import get_settings
from app.db.models.upload_import import UploadImport, UploadImportChunk
from app.db.repositories.station_repository import StationRepository
from app.db.session import get_db
from app.services.upload_import_service import (
    create_import,
    get_import_for_owner,
    import_progress,
)
from app.services.upload_import_storage import (
    import_directory,
    import_file_path,
    persist_upload,
)


router = APIRouter(prefix="/imports", tags=["upload_imports"])


def _ensure_enabled() -> None:
    settings = get_settings()
    if not (settings.BULK_INGESTION_ENABLED and settings.ASYNC_BULK_INGESTION_ENABLED):
        raise HTTPException(status_code=404, detail="Async bulk ingestion is not enabled.")


def _validate_import_id(import_id: str) -> str:
    try:
        return str(UUID(import_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Import not found") from exc


def _get_owned_import(db: Session, import_id: str, current_user: User) -> UploadImport:
    record = get_import_for_owner(db, _validate_import_id(import_id), current_user.username)
    if record is None:
        raise HTTPException(status_code=404, detail="Import not found")
    return record


def _status_response(db: Session, record: UploadImport) -> UploadImportStatusResponse:
    received_chunks, processed_chunks = import_progress(db, record)
    return UploadImportStatusResponse(
        import_id=record.id,
        campaign_id=record.campaign_id,
        station_id=record.station_id,
        total_chunks=record.total_chunks,
        received_chunks=received_chunks,
        processed_chunks=processed_chunks,
        total_bytes=record.total_bytes,
        received_bytes=record.received_bytes,
        rows_read=record.rows_read,
        values_attempted=record.values_attempted,
        values_inserted=record.values_inserted,
        status=cast(ImportStatus, record.status),
        post_processing_status=cast(PostProcessingStatus, record.post_processing_status),
        post_processing_stage=cast(PostProcessingStage | None, record.post_processing_stage),
        post_processing_attempts=record.post_processing_attempts,
        post_processing_error=record.post_processing_error,
        last_error=record.last_error,
        created_at=record.created_at,
        updated_at=record.updated_at,
        sealed_at=record.sealed_at,
        data_loaded_at=record.data_loaded_at,
        post_processing_started_at=record.post_processing_started_at,
        post_processing_completed_at=record.post_processing_completed_at,
        completed_at=record.completed_at,
    )


@router.post("", response_model=UploadImportStatusResponse, status_code=201)
def create_async_import(
    request: UploadImportCreate,
    campaign_id: int,
    station_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_edit_user),
) -> UploadImportStatusResponse:
    _ensure_enabled()
    if not StationRepository(db).station_belongs_to_campaign(station_id, campaign_id):
        raise HTTPException(status_code=404, detail="Station not found")
    settings = get_settings()
    if request.total_chunks > settings.BULK_IMPORT_MAX_CHUNKS:
        raise HTTPException(status_code=413, detail="Import has too many chunks")
    if request.total_bytes > settings.BULK_IMPORT_MAX_TOTAL_BYTES:
        raise HTTPException(status_code=413, detail="Import exceeds the configured byte limit")

    import_id = str(uuid4())
    import_directory(settings, import_id)
    record = create_import(
        db,
        import_id=import_id,
        campaign_id=campaign_id,
        station_id=station_id,
        owner_username=current_user.username,
        total_chunks=request.total_chunks,
        total_bytes=request.total_bytes,
        storage_key=import_id,
    )
    return _status_response(db, record)


@router.post("/{import_id}/chunks", response_model=UploadImportChunkResponse)
def upload_async_import_chunk(
    import_id: str,
    chunk_index: Annotated[int, Form(ge=0)],
    chunk_sha256: Annotated[str, Form()],
    upload_file_measurements: Annotated[
        UploadFile, File(description="One measurement CSV chunk.")
    ],
    upload_file_sensors: Annotated[
        UploadFile | None, File(description="Sensor CSV; required on chunk zero.")
    ] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_edit_user),
) -> UploadImportChunkResponse:
    _ensure_enabled()
    metadata = UploadImportChunkMetadata(
        chunk_index=chunk_index,
        chunk_sha256=chunk_sha256,
    )
    normalized_id = _validate_import_id(import_id)
    record = (
        db.query(UploadImport)
        .filter(UploadImport.id == normalized_id)
        .with_for_update()
        .first()
    )
    if record is None or record.owner_username != current_user.username:
        raise HTTPException(status_code=404, detail="Import not found")
    if record.status not in {"created", "receiving"}:
        raise HTTPException(status_code=409, detail="Import no longer accepts chunks")
    if metadata.chunk_index >= record.total_chunks:
        raise HTTPException(status_code=400, detail="chunk_index is outside the import manifest")

    existing = (
        db.query(UploadImportChunk)
        .filter(
            UploadImportChunk.import_id == record.id,
            UploadImportChunk.chunk_index == metadata.chunk_index,
        )
        .first()
    )
    if existing is not None:
        if existing.sha256 != metadata.chunk_sha256:
            raise HTTPException(status_code=409, detail="Chunk index already has different content")
        return UploadImportChunkResponse(
            import_id=record.id,
            chunk_index=existing.chunk_index,
            byte_size=existing.byte_size,
            sha256=existing.sha256,
            duplicate=True,
            status=cast(ImportStatus, record.status),
        )

    settings = get_settings()
    measurement_path = import_file_path(
        settings, record.storage_key, f"chunk-{metadata.chunk_index}.csv"
    )
    sensors_path: Path | None = None
    try:
        byte_size, actual_sha256 = persist_upload(
            upload_file_measurements,
            measurement_path,
            max_bytes=settings.BULK_IMPORT_MAX_CHUNK_BYTES,
            expected_sha256=metadata.chunk_sha256,
        )
        if record.received_bytes + byte_size > record.total_bytes:
            raise HTTPException(status_code=413, detail="Import exceeds declared total_bytes")
        if metadata.chunk_index == 0 and record.sensors_storage_key is None:
            if upload_file_sensors is None:
                raise HTTPException(status_code=400, detail="Sensor metadata is required on chunk zero")
            sensors_path = import_file_path(settings, record.storage_key, "sensors.csv")
            persist_upload(
                upload_file_sensors,
                sensors_path,
                max_bytes=settings.BULK_IMPORT_MAX_CHUNK_BYTES,
            )
            record.sensors_storage_key = sensors_path.name
        elif upload_file_sensors is not None:
            raise HTTPException(status_code=400, detail="Sensor metadata may only be uploaded on chunk zero")

        now = datetime.now(timezone.utc)
        chunk = UploadImportChunk(
            import_id=record.id,
            chunk_index=metadata.chunk_index,
            byte_size=byte_size,
            sha256=actual_sha256,
            storage_key=measurement_path.name,
            created_at=now,
        )
        db.add(chunk)
        record.received_bytes += byte_size
        record.status = "receiving"
        record.updated_at = now
        db.commit()
    except HTTPException:
        db.rollback()
        try:
            measurement_path.unlink()
        except FileNotFoundError:
            pass
        if sensors_path is not None:
            try:
                sensors_path.unlink()
            except FileNotFoundError:
                pass
        raise
    except Exception as exc:
        db.rollback()
        try:
            measurement_path.unlink()
        except FileNotFoundError:
            pass
        if sensors_path is not None:
            try:
                sensors_path.unlink()
            except FileNotFoundError:
                pass
        raise HTTPException(status_code=500, detail="Could not persist import chunk") from exc
    finally:
        upload_file_measurements.file.close()
        if upload_file_sensors is not None:
            upload_file_sensors.file.close()

    return UploadImportChunkResponse(
        import_id=record.id,
        chunk_index=metadata.chunk_index,
        byte_size=byte_size,
        sha256=actual_sha256,
        status=cast(ImportStatus, record.status),
    )


@router.get("/{import_id}", response_model=UploadImportStatusResponse)
def get_async_import_status(
    import_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_edit_user),
) -> UploadImportStatusResponse:
    _ensure_enabled()
    return _status_response(db, _get_owned_import(db, import_id, current_user))


@router.post("/{import_id}/finalize", response_model=UploadImportFinalizeResponse)
def finalize_async_import(
    import_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_edit_user),
) -> UploadImportFinalizeResponse:
    _ensure_enabled()
    record = (
        db.query(UploadImport)
        .filter(UploadImport.id == _validate_import_id(import_id))
        .with_for_update()
        .first()
    )
    if record is None or record.owner_username != current_user.username:
        raise HTTPException(status_code=404, detail="Import not found")
    if record.status in {"queued", "processing", "data_loaded", "completed"}:
        received_chunks, _ = import_progress(db, record)
        return UploadImportFinalizeResponse(
            import_id=record.id,
            status=cast(FinalizeImportStatus, record.status),
            received_chunks=received_chunks,
            total_chunks=record.total_chunks,
        )
    if record.status == "failed":
        raise HTTPException(status_code=409, detail="Import has failed and cannot be finalized")
    chunks = (
        db.query(UploadImportChunk)
        .filter(UploadImportChunk.import_id == record.id)
        .order_by(UploadImportChunk.chunk_index)
        .all()
    )
    indexes = [chunk.chunk_index for chunk in chunks]
    if indexes != list(range(record.total_chunks)) or record.received_bytes != record.total_bytes:
        raise HTTPException(status_code=409, detail="Import is incomplete")
    if not record.sensors_storage_key:
        raise HTTPException(status_code=409, detail="Sensor metadata is missing")
    now = datetime.now(timezone.utc)
    record.status = "queued"
    record.sealed_at = now
    record.updated_at = now
    db.commit()
    return UploadImportFinalizeResponse(
        import_id=record.id,
        status=cast(FinalizeImportStatus, record.status),
        received_chunks=len(chunks),
        total_chunks=record.total_chunks,
    )
