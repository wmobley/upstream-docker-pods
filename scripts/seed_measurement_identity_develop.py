#!/usr/bin/env python3
"""Seed and activate the measurement identity registry on develop.

Alembic creates the empty identity table and trigger function only. This guarded
helper performs the expensive existing-row seed in resumable batches, validates
the registry, and installs the live-table trigger after the seed completes.

Measurement writers must be paused for the duration of this command.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.session import SessionLocal

IDENTITY_TABLE = "measurement_identity"
STATE_TABLE = "measurement_identity_seed_state"
TRIGGER_FUNCTION = "register_measurement_identity"
TRIGGER_NAME = "measurements_register_identity_before_insert"
DEFAULT_BATCH_SIZE = 100_000


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-develop", action="store_true")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    return parser.parse_args()


def _require_develop(confirm_develop: bool, batch_size: int) -> None:
    if get_settings().ENV != "develop" or not confirm_develop:
        raise RuntimeError(
            "refusing measurement identity seed: require ENV=develop and --confirm-develop"
        )
    if batch_size < 1 or batch_size > 1_000_000:
        raise ValueError("batch size must be between 1 and 1,000,000")


def _ensure_state_table(db: Session) -> None:
    db.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
                seed_key TEXT PRIMARY KEY,
                cursor INTEGER NOT NULL DEFAULT 0,
                phase TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """))
    db.execute(
        text(f"""
            INSERT INTO {STATE_TABLE} (seed_key, cursor, phase, updated_at)
            VALUES ('measurements', 0, 'pending', :updated_at)
            ON CONFLICT (seed_key) DO NOTHING
            """),
        {"updated_at": datetime.now(timezone.utc)},
    )
    db.commit()


def _table_exists(db: Session, name: str) -> bool:
    return bool(
        db.execute(
            text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"public.{name}"}
        ).scalar_one()
    )


def _seed(db: Session, batch_size: int) -> None:
    if not _table_exists(db, IDENTITY_TABLE):
        raise RuntimeError("apply the measurement identity Alembic migration first")
    if not db.execute(
        text("SELECT to_regprocedure(:name) IS NOT NULL"),
        {"name": f"{TRIGGER_FUNCTION}()"},
    ).scalar_one():
        raise RuntimeError("measurement identity trigger function is missing")

    _ensure_state_table(db)
    cursor = int(
        db.execute(
            text(f"SELECT cursor FROM {STATE_TABLE} WHERE seed_key = 'measurements'")
        ).scalar_one()
    )

    invalid = db.execute(text("""
            SELECT COUNT(*)
            FROM measurements
            WHERE measurementid IS NULL OR sensorid IS NULL
            """)).scalar_one()
    if invalid:
        raise RuntimeError(
            f"measurements contains {invalid} null measurement/sensor IDs"
        )

    while True:
        page_max = db.execute(
            text("""
                SELECT MAX(measurementid)
                FROM (
                    SELECT measurementid
                    FROM measurements
                    WHERE measurementid > :cursor
                    ORDER BY measurementid
                    LIMIT :batch_size
                ) page
                """),
            {"cursor": cursor, "batch_size": batch_size},
        ).scalar_one()
        if page_max is None:
            break

        db.execute(
            text(f"""
                INSERT INTO {IDENTITY_TABLE} (measurementid, sensorid)
                SELECT measurementid, sensorid
                FROM measurements
                WHERE measurementid > :cursor AND measurementid <= :page_max
                ON CONFLICT (measurementid) DO NOTHING
                """),
            {"cursor": cursor, "page_max": int(page_max)},
        )
        mismatch = db.execute(
            text(f"""
                SELECT COUNT(*)
                FROM measurements m
                JOIN {IDENTITY_TABLE} i ON i.measurementid = m.measurementid
                WHERE m.measurementid > :cursor
                  AND m.measurementid <= :page_max
                  AND m.sensorid <> i.sensorid
                """),
            {"cursor": cursor, "page_max": int(page_max)},
        ).scalar_one()
        if mismatch:
            raise RuntimeError(
                f"found {mismatch} measurement identity sensor mismatches"
            )

        cursor = int(page_max)
        db.execute(
            text(f"""
                UPDATE {STATE_TABLE}
                SET cursor = :cursor, phase = 'seeding', updated_at = :updated_at
                WHERE seed_key = 'measurements'
                """),
            {"cursor": cursor, "updated_at": datetime.now(timezone.utc)},
        )
        db.commit()
        print({"phase": "seeding", "cursor": cursor}, flush=True)

    source_count = db.execute(text("SELECT COUNT(*) FROM measurements")).scalar_one()
    identity_count = db.execute(
        text(f"SELECT COUNT(*) FROM {IDENTITY_TABLE}")
    ).scalar_one()
    if source_count != identity_count:
        raise RuntimeError(
            f"identity seed count mismatch: measurements={source_count}, identity={identity_count}"
        )

    trigger_exists = db.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgrelid = 'public.measurements'::regclass
                  AND tgname = :trigger_name
                  AND NOT tgisinternal
            )
            """),
        {"trigger_name": TRIGGER_NAME},
    ).scalar_one()
    if not trigger_exists:
        db.execute(text(f"""
                CREATE TRIGGER {TRIGGER_NAME}
                BEFORE INSERT ON measurements
                FOR EACH ROW
                EXECUTE FUNCTION {TRIGGER_FUNCTION}()
                """))
    db.execute(
        text(f"""
            UPDATE {STATE_TABLE}
            SET phase = 'seeded', updated_at = :updated_at
            WHERE seed_key = 'measurements'
            """),
        {"updated_at": datetime.now(timezone.utc)},
    )
    db.commit()
    print({"phase": "seeded", "rows": int(identity_count)}, flush=True)


def main() -> int:
    args = _parse_args()
    _require_develop(args.confirm_develop, args.batch_size)
    db = SessionLocal()
    try:
        _seed(db, args.batch_size)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
