import hashlib
import io
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.routes.upload_file.upload_imports import (
    create_async_import,
    finalize_async_import,
    get_async_import_status,
    upload_async_import_chunk,
)
# Register string-based SQLAlchemy relationships used by the existing models.
import app.db.models.campaign  # noqa: F401,E402
import app.db.models.measurement  # noqa: F401,E402
import app.db.models.note  # noqa: F401,E402
import app.db.models.sensor  # noqa: F401,E402
import app.db.models.station  # noqa: F401,E402

from app.api.v1.schemas.upload_import import UploadImportCreate
from app.core.config import Settings
from app.db.base import Base
from app.db.models.upload_file_event import UploadFileEvent
from app.db.models.upload_import import UploadImport, UploadImportChunk


def make_db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[UploadFileEvent.__table__, UploadImport.__table__, UploadImportChunk.__table__],
    )
    return Session(engine)


def test_async_import_manifest_is_idempotent_and_seals(tmp_path):
    db = make_db()
    user = SimpleNamespace(username="alice")
    settings = Settings(
        BULK_INGESTION_ENABLED=True,
        ASYNC_BULK_INGESTION_ENABLED=True,
        BULK_IMPORT_STORAGE_PATH=str(tmp_path),
    )
    payload = b"collectiontime,Lat_deg,Lon_deg,temp\n2024-01-01T00:00:00Z,30,-97,1\n"
    digest = hashlib.sha256(payload).hexdigest()

    with patch(
        "app.api.v1.routes.upload_file.upload_imports.get_settings", return_value=settings
    ), patch(
        "app.api.v1.routes.upload_file.upload_imports.StationRepository.station_belongs_to_campaign",
        return_value=True,
    ):
        created = create_async_import(
            UploadImportCreate(total_chunks=1, total_bytes=len(payload)),
            campaign_id=1,
            station_id=2,
            db=db,
            current_user=user,
        )
        import_id = created.import_id
        first = upload_async_import_chunk(
            import_id,
            chunk_index=0,
            chunk_sha256=digest,
            upload_file_measurements=UploadFile(
                file=io.BytesIO(payload), filename="client.csv"
            ),
            upload_file_sensors=UploadFile(
                file=io.BytesIO(b"alias,variablename,units\ntemp,T,C\n"),
                filename="client-sensors.csv",
            ),
            db=db,
            current_user=user,
        )
        duplicate = upload_async_import_chunk(
            import_id,
            chunk_index=0,
            chunk_sha256=digest,
            upload_file_measurements=UploadFile(
                file=io.BytesIO(payload), filename="retry.csv"
            ),
            db=db,
            current_user=user,
        )
        finalized = finalize_async_import(import_id, db=db, current_user=user)
        status = get_async_import_status(import_id, db=db, current_user=user)

    assert first.duplicate is False
    assert duplicate.duplicate is True
    assert finalized.status == "queued"
    assert status.received_chunks == 1
    assert status.processed_chunks == 0
    assert status.status == "queued"
