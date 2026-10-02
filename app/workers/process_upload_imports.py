"""Process queued async bulk imports.

Run from the API environment with the same database and import storage mount:

    python -m app.workers.process_upload_imports --import-id <uuid>
    python -m app.workers.process_upload_imports --poll
"""

import argparse
import logging
import signal
import threading
from collections.abc import Callable
from types import FrameType

from app.core.config import get_settings
# Register string-based SQLAlchemy relationships when the worker is launched
# directly rather than through app.main.
import app.db.models.campaign  # noqa: F401,E402
import app.db.models.measurement  # noqa: F401,E402
import app.db.models.note  # noqa: F401,E402
import app.db.models.sensor  # noqa: F401,E402
import app.db.models.station  # noqa: F401,E402

from app.db.session import SessionLocal
from app.services.upload_import_service import (
    UploadImportLeaseLost,
    claim_import,
    mark_import_failure,
    post_process_claimed_import,
    process_claimed_import,
)
from app.services.upload_import_storage import cleanup_import_storage


logger = logging.getLogger(__name__)


def _validate_poll_seconds(value: float) -> float:
    if value <= 0 or value > 3600:
        raise ValueError("poll interval must be greater than 0 and no more than 3600 seconds")
    return value


def run_once(import_id: str | None = None) -> int:
    settings = get_settings()
    if not (settings.BULK_INGESTION_ENABLED and settings.ASYNC_BULK_INGESTION_ENABLED):
        logger.error("Async bulk ingestion is not enabled")
        return 2
    try:
        db = SessionLocal()
        try:
            claimed = claim_import(db, settings, import_id=import_id)
            if claimed is None:
                logger.info("No queued import available")
                return 0
            record, worker_token = claimed
            try:
                record, alias_to_sensorid = process_claimed_import(db, settings, record, worker_token)
                post_process_claimed_import(
                    db, settings, record, worker_token, alias_to_sensorid
                )
                logger.info("Completed async import %s", record.id)
                try:
                    cleanup_import_storage(settings, record.storage_key, status="completed")
                except Exception:
                    logger.exception("Could not clean up completed import %s storage", record.id)
                return 0
            except UploadImportLeaseLost:
                db.rollback()
                logger.warning("Lost lease while processing async import %s", record.id)
                return 3
            except Exception as exc:
                db.rollback()
                logger.exception("Async import %s failed", record.id)
                terminal = mark_import_failure(db, settings, record.id, worker_token, exc)
                if terminal:
                    try:
                        cleanup_import_storage(settings, record.storage_key, status="failed")
                    except Exception:
                        logger.exception("Could not clean up failed import %s storage", record.id)
                return 1
        finally:
            db.close()
    except Exception:
        logger.exception("Unable to claim an async import")
        return 1


def run_loop(
    *,
    poll_seconds: float | None = None,
    stop_event: threading.Event | None = None,
    run_once_fn: Callable[[], int] | None = None,
) -> int:
    """Continuously claim queued imports until asked to shut down.

    The one-shot ``run_once`` mode remains the diagnostic/default entry point.
    Polling is explicitly opt-in and never claims work while either async flag
    is disabled. ``Event.wait`` keeps SIGTERM responsive while idle.
    """
    settings = get_settings()
    interval = _validate_poll_seconds(
        settings.BULK_IMPORT_WORKER_POLL_SECONDS if poll_seconds is None else poll_seconds
    )
    shutdown = stop_event or threading.Event()
    process_once = run_once_fn or (lambda: run_once())

    if not (settings.BULK_INGESTION_ENABLED and settings.ASYNC_BULK_INGESTION_ENABLED):
        logger.warning("Async bulk ingestion is disabled; worker will remain idle")

    while not shutdown.is_set():
        if settings.BULK_INGESTION_ENABLED and settings.ASYNC_BULK_INGESTION_ENABLED:
            result = process_once()
            if result == 2:
                logger.warning("Async bulk ingestion became disabled; worker is idle")
        if shutdown.wait(interval):
            break

    logger.info("Async import worker shutting down")
    return 0


SignalHandler = signal.Handlers | Callable[[int, FrameType | None], object] | int | None


def _install_shutdown_handlers(stop_event: threading.Event) -> dict[int, SignalHandler]:
    previous: dict[int, SignalHandler] = {}

    def request_shutdown(signum: int, _frame: FrameType | None) -> None:
        logger.info("Received signal %s; stopping after the current claim", signum)
        stop_event.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, request_shutdown)
    return previous


def _restore_shutdown_handlers(previous: dict[int, SignalHandler]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process one Upstream async bulk import")
    parser.add_argument("--import-id", default=None)
    parser.add_argument("--poll", action="store_true", help="continuously process queued imports")
    parser.add_argument("--poll-seconds", type=float, default=None)
    args = parser.parse_args()
    if args.poll and args.import_id:
        parser.error("--poll and --import-id cannot be used together")
    if args.poll:
        stop_event = threading.Event()
        previous = _install_shutdown_handlers(stop_event)
        try:
            raise SystemExit(run_loop(poll_seconds=args.poll_seconds, stop_event=stop_event))
        finally:
            _restore_shutdown_handlers(previous)
    raise SystemExit(run_once(args.import_id))


if __name__ == "__main__":
    main()
