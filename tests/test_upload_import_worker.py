from datetime import datetime, timedelta, timezone
import threading
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
# Register string-based SQLAlchemy relationships used by the existing models.
import app.db.models.campaign  # noqa: F401,E402
import app.db.models.measurement  # noqa: F401,E402
import app.db.models.note  # noqa: F401,E402
import app.db.models.sensor  # noqa: F401,E402
import app.db.models.station  # noqa: F401,E402

from app.db.base import Base
from app.db.models.upload_file_event import UploadFileEvent
from app.db.models.upload_import import UploadImport, UploadImportChunk
from app.services.upload_import_service import (
    UploadImportLeaseLost,
    claim_import,
    heartbeat,
    mark_import_failure,
    process_claimed_import,
)
from app.workers import process_upload_imports as worker


def make_worker_db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[UploadFileEvent.__table__, UploadImport.__table__, UploadImportChunk.__table__],
    )
    return Session(engine)


def test_worker_claim_heartbeat_and_retry_state_are_durable():
    db = make_worker_db()
    now = datetime.now(timezone.utc)
    db.add(
        UploadImport(
            id="import-1",
            campaign_id=1,
            station_id=2,
            owner_username="alice",
            total_chunks=1,
            total_bytes=10,
            status="queued",
            storage_key="import-1",
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    settings = Settings(BULK_IMPORT_WORKER_LEASE_SECONDS=60, BULK_IMPORT_MAX_ATTEMPTS=2)

    claimed = claim_import(db, settings, import_id="import-1")
    assert claimed is not None
    record, worker_token = claimed
    assert record.status == "processing"
    assert record.attempts == 1
    heartbeat(db, settings, record.id, worker_token)
    mark_import_failure(db, settings, record.id, worker_token, RuntimeError("temporary"))

    refreshed = db.get(UploadImport, "import-1")
    assert refreshed is not None
    assert refreshed.status == "queued"
    assert refreshed.last_error == "RuntimeError: import processing failed"
    assert refreshed.worker_token is None


def test_poll_worker_stays_idle_when_flags_are_disabled(monkeypatch):
    settings = Settings(
        BULK_INGESTION_ENABLED=False,
        ASYNC_BULK_INGESTION_ENABLED=False,
        BULK_IMPORT_WORKER_POLL_SECONDS=0.01,
    )
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    stop_event = threading.Event()
    thread = threading.Thread(
        target=worker.run_loop,
        kwargs={"stop_event": stop_event, "poll_seconds": 0.01},
    )
    started = time.monotonic()
    thread.start()
    time.sleep(0.03)
    stop_event.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert time.monotonic() - started < 1


def test_poll_worker_processes_until_shutdown(monkeypatch):
    settings = Settings(
        BULK_INGESTION_ENABLED=True,
        ASYNC_BULK_INGESTION_ENABLED=True,
        BULK_IMPORT_WORKER_POLL_SECONDS=0.01,
    )
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    stop_event = threading.Event()
    calls: list[int] = []

    def fake_run_once() -> int:
        calls.append(1)
        stop_event.set()
        return 0

    assert worker.run_loop(
        stop_event=stop_event,
        poll_seconds=0.01,
        run_once_fn=fake_run_once,
    ) == 0
    assert calls == [1]


def test_run_once_separates_chunk_processing_from_post_processing(monkeypatch):
    settings = Settings(
        BULK_INGESTION_ENABLED=True,
        ASYNC_BULK_INGESTION_ENABLED=True,
    )
    monkeypatch.setattr(worker, "get_settings", lambda: settings)

    class FakeDB:
        def close(self):
            pass

        def rollback(self):
            pass

    record = SimpleNamespace(id="import-1", storage_key="import-1")
    monkeypatch.setattr(worker, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(worker, "claim_import", lambda db, settings, import_id=None: (record, "token"))
    calls: list[str] = []

    def process_chunks(db, settings, claimed_record, token):
        calls.append("chunks")
        return claimed_record, {}

    monkeypatch.setattr(
        worker,
        "process_claimed_import",
        process_chunks,
    )
    monkeypatch.setattr(
        worker,
        "post_process_claimed_import",
        lambda db, settings, record, token, alias_to_sensorid: calls.append("post-processing"),
    )
    monkeypatch.setattr(worker, "cleanup_import_storage", lambda *args, **kwargs: None)

    assert worker.run_once() == 0
    assert calls == ["chunks", "post-processing"]


def test_poll_interval_must_be_positive_and_bounded():
    with pytest.raises(ValueError):
        worker._validate_poll_seconds(0)
    with pytest.raises(ValueError):
        worker._validate_poll_seconds(3601)


def test_reclaimed_import_rejects_stale_worker_before_processing():
    db = make_worker_db()
    now = datetime.now(timezone.utc)
    db.add(
        UploadImport(
            id="import-stale",
            campaign_id=1,
            station_id=2,
            owner_username="alice",
            total_chunks=1,
            total_bytes=10,
            status="queued",
            storage_key="import-stale",
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    settings = Settings(BULK_IMPORT_WORKER_LEASE_SECONDS=60)

    first = claim_import(db, settings, import_id="import-stale")
    assert first is not None
    stale_record, stale_token = first
    stale_record.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    second = claim_import(db, settings, import_id="import-stale")
    assert second is not None
    reclaimed_record, reclaimed_token = second
    assert reclaimed_token != stale_token
    assert reclaimed_record.worker_token == reclaimed_token

    with pytest.raises(UploadImportLeaseLost):
        process_claimed_import(db, settings, stale_record, stale_token)
