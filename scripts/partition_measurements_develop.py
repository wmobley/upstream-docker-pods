#!/usr/bin/env python3
"""Prepare and cut over a sensor-partitioned measurements table on develop.

This command is intentionally opt-in and refuses to run outside an ``ENV=develop``
container.  ``prepare`` copies and indexes one sensor-hash partition at a time and
records durable cursors, so rerunning the same command resumes after an interruption.
It assumes measurement writers are paused for ``cutover`` and keeps the old table
under a recovery name; it never drops the legacy table automatically.

Examples (inside the develop API container):

    python scripts/partition_measurements_develop.py --confirm-develop prepare
    python scripts/partition_measurements_develop.py --confirm-develop status
    python scripts/partition_measurements_develop.py --confirm-develop cutover
    python scripts/partition_measurements_develop.py --confirm-develop rollback
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.session import SessionLocal

PARTITION_COUNT = 16
COPY_COLUMNS = (
    "measurementid, sensorid, stationid, variablename, collectiontime, "
    "variabletype, description, measurementvalue, geometry, "
    "upload_file_events_id, is_published, published_at"
)
SOURCE_TABLE = "measurements"
SHADOW_TABLE = "measurements_partitioned_shadow"
LEGACY_TABLE = "measurements_legacy_20261006"
FAILED_TABLE = "measurements_partitioned_failed_20261006"
STATE_TABLE = "measurement_partition_migration"
ADVISORY_LOCK_KEY = "upstream.measurements.partition.cutover"

LIVE_INDEXES = {
    "pkey": "measurements_pkey",
    "sensor_time": "uq_measurements_sensor_time",
    "geometry": "idx_measurements_geometry",
}
LEGACY_INDEXES = {
    "pkey": "measurements_legacy_20261006_pkey",
    "sensor_time": "measurements_legacy_20261006_sensor_time",
    "geometry": "measurements_legacy_20261006_geometry",
}
SHADOW_INDEXES = {
    "pkey": "measurements_partitioned_shadow_measurementid_sensor_uq",
    "sensor_time": "measurements_partitioned_shadow_sensor_time_uq",
    "geometry": "measurements_partitioned_shadow_geometry_idx",
}
INDEX_KEYS = ("pkey", "sensor_time", "geometry")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-develop",
        action="store_true",
        help="Required guard confirming this is an intentional develop operation.",
    )
    parser.add_argument(
        "action",
        choices=("prepare", "status", "cutover", "rollback"),
    )
    return parser.parse_args()


def _quote(name: str) -> str:
    if not name.replace("_", "").isalnum() or name[0].isdigit():
        raise ValueError(f"unsafe SQL identifier: {name}")
    return f'"{name}"'


def _require_develop(confirm_develop: bool) -> None:
    settings = get_settings()
    if settings.ENV != "develop" or not confirm_develop:
        raise RuntimeError(
            "refusing measurement partition operation: require ENV=develop and "
            "--confirm-develop"
        )


def _ensure_state_table(db) -> None:  # type: ignore[no-untyped-def]
    db.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {_quote(STATE_TABLE)} (
                migration_key TEXT PRIMARY KEY,
                phase TEXT NOT NULL,
                source_table TEXT NOT NULL,
                shadow_table TEXT NOT NULL,
                legacy_table TEXT NOT NULL,
                copy_cursor INTEGER NOT NULL DEFAULT -1,
                index_cursor INTEGER NOT NULL DEFAULT -1,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """))
    db.execute(
        text(
            f"ALTER TABLE {_quote(STATE_TABLE)} "
            "ADD COLUMN IF NOT EXISTS copy_cursor INTEGER NOT NULL DEFAULT -1"
        )
    )
    db.execute(
        text(
            f"ALTER TABLE {_quote(STATE_TABLE)} "
            "ADD COLUMN IF NOT EXISTS index_cursor INTEGER NOT NULL DEFAULT -1"
        )
    )
    db.commit()


def _set_phase(
    db: Any,
    phase: str,
    *,
    copy_cursor: int | None = None,
    index_cursor: int | None = None,
) -> None:
    current = db.execute(
        text(
            f"SELECT copy_cursor, index_cursor FROM {_quote(STATE_TABLE)} "
            "WHERE migration_key = 'measurements'"
        )
    ).one_or_none()
    resolved_copy_cursor = (
        copy_cursor if copy_cursor is not None else (current[0] if current else -1)
    )
    resolved_index_cursor = (
        index_cursor if index_cursor is not None else (current[1] if current else -1)
    )
    db.execute(
        text(f"""
            INSERT INTO {_quote(STATE_TABLE)}
                (migration_key, phase, source_table, shadow_table, legacy_table,
                 copy_cursor, index_cursor, updated_at)
            VALUES
                (:migration_key, :phase, :source_table, :shadow_table, :legacy_table,
                 :copy_cursor, :index_cursor, :updated_at)
            ON CONFLICT (migration_key) DO UPDATE SET
                phase = EXCLUDED.phase,
                copy_cursor = EXCLUDED.copy_cursor,
                index_cursor = EXCLUDED.index_cursor,
                updated_at = EXCLUDED.updated_at
            """),
        {
            "migration_key": "measurements",
            "phase": phase,
            "source_table": SOURCE_TABLE,
            "shadow_table": SHADOW_TABLE,
            "legacy_table": LEGACY_TABLE,
            "copy_cursor": resolved_copy_cursor,
            "index_cursor": resolved_index_cursor,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    db.commit()


def _table_exists(db, name: str) -> bool:  # type: ignore[no-untyped-def]
    return bool(
        db.execute(
            text("SELECT to_regclass(:name) IS NOT NULL"),
            {"name": f"public.{name}"},
        ).scalar_one()
    )


def _create_shadow(db) -> None:  # type: ignore[no-untyped-def]
    if _table_exists(db, LEGACY_TABLE):
        raise RuntimeError("a legacy measurements table already exists")
    if _table_exists(db, SHADOW_TABLE):
        raise RuntimeError(
            "a shadow measurements table already exists without migration state"
        )
    if not _table_exists(db, "measurement_identity"):
        raise RuntimeError("measurement_identity migration must be applied first")

    db.execute(text(f"""
            CREATE TABLE {_quote(SHADOW_TABLE)} (
                measurementid INTEGER NOT NULL DEFAULT nextval('measurements_measurementid_seq'::regclass),
                sensorid INTEGER NOT NULL,
                stationid INTEGER,
                variablename VARCHAR,
                collectiontime TIMESTAMPTZ,
                variabletype VARCHAR,
                description VARCHAR,
                measurementvalue DOUBLE PRECISION NOT NULL,
                geometry geometry(POINT, 4326) NOT NULL,
                upload_file_events_id INTEGER,
                is_published BOOLEAN NOT NULL DEFAULT FALSE,
                published_at TIMESTAMPTZ,
                CONSTRAINT measurements_partitioned_shadow_sensor_fk
                    FOREIGN KEY (sensorid) REFERENCES sensors(sensorid) ON DELETE CASCADE,
                CONSTRAINT measurements_partitioned_shadow_upload_event_fk
                    FOREIGN KEY (upload_file_events_id) REFERENCES upload_file_events(id) ON DELETE CASCADE,
                CONSTRAINT measurements_partitioned_shadow_identity_fk
                    FOREIGN KEY (measurementid) REFERENCES measurement_identity(measurementid)
            ) PARTITION BY HASH (sensorid)
            """))
    for remainder in range(PARTITION_COUNT):
        db.execute(text(f"""
                CREATE TABLE {_quote(f'{SHADOW_TABLE}_p{remainder}')}
                PARTITION OF {_quote(SHADOW_TABLE)}
                FOR VALUES WITH (MODULUS {PARTITION_COUNT}, REMAINDER {remainder})
                """))


def _validate_source(db) -> None:  # type: ignore[no-untyped-def]
    invalid = db.execute(
        text(
            f"SELECT COUNT(*) FROM {_quote(SOURCE_TABLE)} "
            "WHERE measurementid IS NULL OR sensorid IS NULL"
        )
    ).scalar_one()
    if invalid:
        raise RuntimeError(f"source contains {invalid} null measurement or sensor IDs")


def _partition_table_name(remainder: int) -> str:
    if remainder < 0 or remainder >= PARTITION_COUNT:
        raise ValueError(f"invalid partition remainder: {remainder}")
    return f"{SHADOW_TABLE}_p{remainder}"


def _partition_predicate() -> str:
    return (
        f"(((hashint4(sensorid) % {PARTITION_COUNT}) + {PARTITION_COUNT}) "
        f"% {PARTITION_COUNT}) = :remainder"
    )


def _copy_partition(db, remainder: int) -> None:  # type: ignore[no-untyped-def]
    target = _quote(_partition_table_name(remainder))
    db.execute(
        text(
            f"INSERT INTO {target} ({COPY_COLUMNS}) "
            f"SELECT {COPY_COLUMNS} FROM {_quote(SOURCE_TABLE)} "
            f"WHERE {_partition_predicate()}"
        ),
        {"remainder": remainder},
    )


def _local_index_name(index_key: str, remainder: int) -> str:
    return f"{SHADOW_TABLE}_p{remainder}_{index_key}_idx"


def _create_partition_index(
    db: Any, index_key: str, remainder: int
) -> None:
    table = _quote(_partition_table_name(remainder))
    index_name = _quote(_local_index_name(index_key, remainder))
    definitions = {
        "pkey": f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table} (measurementid, sensorid)",
        "sensor_time": f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table} (sensorid, collectiontime)",
        "geometry": f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} USING GIST (geometry)",
    }
    db.execute(text(definitions[index_key]))


def _index_attached(db, parent: str, child: str) -> bool:  # type: ignore[no-untyped-def]
    return bool(
        db.execute(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM pg_inherits "
                "WHERE inhparent = CAST(:parent AS regclass) "
                "AND inhrelid = CAST(:child AS regclass))"
            ),
            {"parent": f"public.{parent}", "child": f"public.{child}"},
        ).scalar_one()
    )


def _ensure_parent_indexes(db) -> None:  # type: ignore[no-untyped-def]
    definitions = {
        "pkey": (
            f"CREATE UNIQUE INDEX IF NOT EXISTS {_quote(SHADOW_INDEXES['pkey'])} "
            f"ON ONLY {_quote(SHADOW_TABLE)} (measurementid, sensorid)"
        ),
        "sensor_time": (
            f"CREATE UNIQUE INDEX IF NOT EXISTS {_quote(SHADOW_INDEXES['sensor_time'])} "
            f"ON ONLY {_quote(SHADOW_TABLE)} (sensorid, collectiontime)"
        ),
        "geometry": (
            f"CREATE INDEX IF NOT EXISTS {_quote(SHADOW_INDEXES['geometry'])} "
            f"ON ONLY {_quote(SHADOW_TABLE)} USING GIST (geometry)"
        ),
    }
    for index_key in INDEX_KEYS:
        db.execute(text(definitions[index_key]))
        parent = SHADOW_INDEXES[index_key]
        for remainder in range(PARTITION_COUNT):
            child = _local_index_name(index_key, remainder)
            if not _index_attached(db, parent, child):
                db.execute(
                    text(
                        f"ALTER INDEX {_quote(parent)} "
                        f"ATTACH PARTITION {_quote(child)}"
                    )
                )
        db.commit()


def _ensure_shadow_trigger(db) -> None:  # type: ignore[no-untyped-def]
    trigger_name = "measurements_partitioned_register_identity_before_insert"
    exists = db.execute(
        text(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_trigger "
            "WHERE tgrelid = CAST(:table_name AS regclass) "
            "AND tgname = :trigger_name AND NOT tgisinternal)"
        ),
        {"table_name": f"public.{SHADOW_TABLE}", "trigger_name": trigger_name},
    ).scalar_one()
    if not exists:
        db.execute(
            text(
                f"CREATE TRIGGER {_quote(trigger_name)} "
                f"BEFORE INSERT ON {_quote(SHADOW_TABLE)} FOR EACH ROW "
                "EXECUTE FUNCTION register_measurement_identity()"
            )
        )
    db.commit()


def _validate_shadow(db) -> None:  # type: ignore[no-untyped-def]
    source_count = db.execute(
        text(f"SELECT COUNT(*) FROM {_quote(SOURCE_TABLE)}")
    ).scalar_one()
    shadow_count = db.execute(
        text(f"SELECT COUNT(*) FROM {_quote(SHADOW_TABLE)}")
    ).scalar_one()
    missing_identity = db.execute(text(f"""
            SELECT COUNT(*)
            FROM {_quote(SHADOW_TABLE)} m
            LEFT JOIN measurement_identity i ON i.measurementid = m.measurementid
            WHERE i.measurementid IS NULL
            """)).scalar_one()
    if source_count != shadow_count or missing_identity:
        raise RuntimeError(
            f"shadow validation failed: source={source_count}, shadow={shadow_count}, "
            f"missing_identity={missing_identity}"
        )


def _prepare(db) -> None:  # type: ignore[no-untyped-def]
    _ensure_state_table(db)
    state = db.execute(
        text(
            f"SELECT phase, copy_cursor, index_cursor FROM {_quote(STATE_TABLE)} "
            "WHERE migration_key = 'measurements'"
        )
    ).one_or_none()
    if state is None:
        _validate_source(db)
        _create_shadow(db)
        _set_phase(db, "copying", copy_cursor=-1, index_cursor=-1)
        state = ("copying", -1, -1)

    phase, copy_cursor, index_cursor = state
    if phase == "prepared":
        print("partitioned measurements shadow table is already prepared")
        return
    if phase not in {"copying", "indexing", "validating"}:
        raise RuntimeError(f"prepare cannot resume from phase {phase!r}")

    if phase == "copying":
        for remainder in range(int(copy_cursor) + 1, PARTITION_COUNT):
            _copy_partition(db, remainder)
            _set_phase(db, "copying", copy_cursor=remainder, index_cursor=-1)
            print({"phase": "copying", "partition": remainder}, flush=True)
        _set_phase(db, "indexing", copy_cursor=PARTITION_COUNT - 1, index_cursor=-1)
        phase = "indexing"
        index_cursor = -1

    if phase == "indexing":
        for step in range(int(index_cursor) + 1, PARTITION_COUNT * len(INDEX_KEYS)):
            index_key = INDEX_KEYS[step // PARTITION_COUNT]
            remainder = step % PARTITION_COUNT
            _create_partition_index(db, index_key, remainder)
            db.commit()
            _set_phase(
                db,
                "indexing",
                copy_cursor=PARTITION_COUNT - 1,
                index_cursor=step,
            )
            print(
                {"phase": "indexing", "index": index_key, "partition": remainder},
                flush=True,
            )
        _ensure_parent_indexes(db)
        _ensure_shadow_trigger(db)
        _set_phase(
            db,
            "validating",
            copy_cursor=PARTITION_COUNT - 1,
            index_cursor=PARTITION_COUNT * len(INDEX_KEYS) - 1,
        )

    _validate_shadow(db)
    _set_phase(db, "prepared")
    print("prepared and validated partitioned measurements shadow table")


def _rename_index(db, old: str, new: str) -> None:  # type: ignore[no-untyped-def]
    db.execute(text(f"ALTER INDEX {_quote(old)} RENAME TO {_quote(new)}"))


def _cutover(db) -> None:  # type: ignore[no-untyped-def]
    _ensure_state_table(db)
    phase = db.execute(
        text(
            f"SELECT phase FROM {_quote(STATE_TABLE)} WHERE migration_key = 'measurements'"
        )
    ).scalar_one_or_none()
    if phase != "prepared":
        raise RuntimeError(f"cutover requires prepared phase, found {phase!r}")
    _validate_shadow(db)

    db.execute(
        text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"),
        {"key": ADVISORY_LOCK_KEY},
    )
    try:
        db.execute(
            text(
                "ALTER TABLE notes DROP CONSTRAINT IF EXISTS notes_measurement_id_fkey"
            )
        )
        for key in LIVE_INDEXES:
            _rename_index(db, LIVE_INDEXES[key], LEGACY_INDEXES[key])
        db.execute(
            text(f"ALTER TABLE {_quote(SOURCE_TABLE)} RENAME TO {_quote(LEGACY_TABLE)}")
        )
        db.execute(
            text(f"ALTER TABLE {_quote(SHADOW_TABLE)} RENAME TO {_quote(SOURCE_TABLE)}")
        )
        for key in SHADOW_INDEXES:
            canonical = LIVE_INDEXES[key]
            _rename_index(db, SHADOW_INDEXES[key], canonical)
        db.execute(text(f"""
                ALTER TABLE notes
                ADD CONSTRAINT notes_measurement_id_fkey
                FOREIGN KEY (measurement_id)
                REFERENCES measurement_identity(measurementid)
                ON DELETE CASCADE
                """))
        db.commit()
        _set_phase(db, "cutover")
        print(f"cutover complete; legacy table retained as {LEGACY_TABLE}")
    finally:
        db.execute(
            text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
            {"key": ADVISORY_LOCK_KEY},
        )
        db.commit()


def _rollback(db) -> None:  # type: ignore[no-untyped-def]
    _ensure_state_table(db)
    phase = db.execute(
        text(
            f"SELECT phase FROM {_quote(STATE_TABLE)} WHERE migration_key = 'measurements'"
        )
    ).scalar_one_or_none()
    if phase != "cutover":
        raise RuntimeError(f"rollback requires cutover phase, found {phase!r}")
    if not _table_exists(db, LEGACY_TABLE) or not _table_exists(db, SOURCE_TABLE):
        raise RuntimeError("rollback requires both current and legacy tables")

    db.execute(
        text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"),
        {"key": ADVISORY_LOCK_KEY},
    )
    try:
        db.execute(
            text(
                "ALTER TABLE notes DROP CONSTRAINT IF EXISTS notes_measurement_id_fkey"
            )
        )
        for key in LIVE_INDEXES:
            _rename_index(db, LIVE_INDEXES[key], f"measurements_failed_20261006_{key}")
        db.execute(
            text(f"ALTER TABLE {_quote(SOURCE_TABLE)} RENAME TO {_quote(FAILED_TABLE)}")
        )
        db.execute(
            text(f"ALTER TABLE {_quote(LEGACY_TABLE)} RENAME TO {_quote(SOURCE_TABLE)}")
        )
        for key in LEGACY_INDEXES:
            _rename_index(db, LEGACY_INDEXES[key], LIVE_INDEXES[key])
        db.execute(text(f"""
                ALTER TABLE notes
                ADD CONSTRAINT notes_measurement_id_fkey
                FOREIGN KEY (measurement_id)
                REFERENCES measurements(measurementid)
                ON DELETE CASCADE
                """))
        db.commit()
        _set_phase(db, "rolled_back")
        print(f"rollback complete; failed partitioned table retained as {FAILED_TABLE}")
    finally:
        db.execute(
            text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
            {"key": ADVISORY_LOCK_KEY},
        )
        db.commit()


def _status(db) -> None:  # type: ignore[no-untyped-def]
    _ensure_state_table(db)
    row = db.execute(
        text(
            f"SELECT phase, copy_cursor, index_cursor, updated_at FROM {_quote(STATE_TABLE)} "
            "WHERE migration_key = 'measurements'"
        )
    ).one_or_none()
    print(
        {
            "phase": row[0] if row else None,
            "copy_cursor": row[1] if row else None,
            "index_cursor": row[2] if row else None,
            "updated_at": row[3].isoformat() if row else None,
            "source_exists": _table_exists(db, SOURCE_TABLE),
            "shadow_exists": _table_exists(db, SHADOW_TABLE),
            "legacy_exists": _table_exists(db, LEGACY_TABLE),
            "failed_exists": _table_exists(db, FAILED_TABLE),
        }
    )


def main() -> int:
    args = _parse_args()
    _require_develop(args.confirm_develop)
    db = SessionLocal()
    try:
        if args.action == "prepare":
            _prepare(db)
        elif args.action == "status":
            _status(db)
        elif args.action == "cutover":
            _cutover(db)
        else:
            _rollback(db)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
