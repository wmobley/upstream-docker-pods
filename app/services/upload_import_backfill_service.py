"""Isolated, opt-in shadow-table processing for historical imports."""

import csv
import io
import re
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models.upload_import import UploadImport, UploadImportChunk
from app.db.models.upload_import_backfill import UploadImportBackfill
from app.db.models.upload_file_event import UploadFileEvent
from app.utils.bulk_upload_csv import _parse_stage_row


_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,126}$")


def _quote_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError("Invalid server-generated backfill table name")
    return f'"{value}"'


def _table_names(import_id: str) -> tuple[str, str]:
    token = UUID(import_id).hex
    return f"upload_backfill_raw_{token}", f"upload_backfill_shadow_{token}"


def _shadow_index_name(table_name: str) -> str:
    return f"ubf_{table_name[-32:]}_sensor_time_uq"


def _materialize_bucket_predicate(bucket_count: int) -> str:
    if bucket_count <= 0:
        raise ValueError("bucket_count must be positive")
    return (
        "mod(mod(sensor_value.key::INTEGER, :bucket_count) + :bucket_count, "
        ":bucket_count) = :bucket"
    )


def _station_lock(session: Session, station_id: int) -> None:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"upstream.measurements.station.{station_id}"},
    )


def ensure_backfill_state(session: Session, record: UploadImport) -> UploadImportBackfill:
    state = (
        session.query(UploadImportBackfill)
        .filter(UploadImportBackfill.import_id == record.id)
        .with_for_update()
        .first()
    )
    raw_name, shadow_name = _table_names(record.id)
    if state is None:
        state = UploadImportBackfill(
            import_id=record.id,
            raw_table_name=raw_name,
            shadow_table_name=shadow_name,
            phase="staging",
            created_at=datetime.now().astimezone(),
            updated_at=datetime.now().astimezone(),
        )
        session.add(state)
        session.flush()

    raw = _quote_identifier(state.raw_table_name)
    shadow = _quote_identifier(state.shadow_table_name)
    session.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {raw} (
                source_chunk_index INTEGER NOT NULL,
                source_row_ordinal BIGINT NOT NULL,
                stationid INTEGER NOT NULL,
                collectiontime TIMESTAMPTZ NOT NULL,
                lat DOUBLE PRECISION NOT NULL,
                lon DOUBLE PRECISION NOT NULL,
                sensor_values JSONB NOT NULL,
                upload_file_event_id INTEGER NOT NULL,
                PRIMARY KEY (source_chunk_index, source_row_ordinal)
            )
            """
        )
    )
    session.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {shadow} (
                shadow_row_id BIGSERIAL PRIMARY KEY,
                stationid INTEGER NOT NULL,
                collectiontime TIMESTAMPTZ NOT NULL,
                measurementvalue DOUBLE PRECISION NOT NULL,
                geometry geometry(POINT, 4326) NOT NULL,
                sensorid INTEGER NOT NULL,
                variablename TEXT,
                upload_file_event_id INTEGER NOT NULL
            )
            """
        )
    )
    session.commit()
    return state


def _stage_rows(
    session: Session,
    state: UploadImportBackfill,
    record: UploadImport,
    chunk: UploadImportChunk,
    event: UploadFileEvent,
    measurement_path: Any,
    alias_to_sensorid: dict[str, int],
    station_timezone: str,
    batch_size: int,
) -> tuple[int, int]:
    if not alias_to_sensorid:
        return 0, 0
    raw = _quote_identifier(state.raw_table_name)
    insert = text(
        f"""
        INSERT INTO {raw}
            (source_chunk_index, source_row_ordinal, stationid, collectiontime,
             lat, lon, sensor_values, upload_file_event_id)
        VALUES
            (:source_chunk_index, :source_row_ordinal, :stationid, :collectiontime,
             :lat, :lon, :sensor_values, :upload_file_event_id)
        ON CONFLICT (source_chunk_index, source_row_ordinal) DO NOTHING
        """
    ).bindparams(bindparam("sensor_values", type_=JSONB))

    with measurement_path.open("rb") as handle:
        stream = io.TextIOWrapper(handle, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        missing = sorted({"collectiontime", "Lat_deg", "Lon_deg"} - set(fields))
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Measurements CSV is missing required column(s): {missing}",
            )
        usable = {alias: sensor_id for alias, sensor_id in alias_to_sensorid.items() if alias in fields}
        if not usable:
            raise HTTPException(status_code=400, detail="Measurements CSV has no mapped sensor columns")
        batch: list[dict[str, Any]] = []
        for row_ordinal, row in enumerate(reader):
            parsed = _parse_stage_row(
                row,
                source_row_ordinal=row_ordinal,
                station_id=record.station_id,
                alias_to_sensorid_map=usable,
                station_timezone=station_timezone,
                per_alias={},
            )
            batch.append(
                {
                    "source_chunk_index": chunk.chunk_index,
                    "source_row_ordinal": row_ordinal,
                    "stationid": parsed["stationid"],
                    "collectiontime": parsed["collectiontime"],
                    "lat": float(parsed["lat"]),
                    "lon": float(parsed["lon"]),
                    "sensor_values": parsed["sensor_values"],
                    "upload_file_event_id": event.id,
                }
            )
            if not -90 <= batch[-1]["lat"] <= 90 or not -180 <= batch[-1]["lon"] <= 180:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid coordinates on measurement row {row_ordinal}",
                )
            if len(batch) >= batch_size:
                session.execute(insert, batch)
                batch.clear()
        if batch:
            session.execute(insert, batch)
    counts = session.execute(
        text(
            f"""
            SELECT COUNT(*) AS rows,
                   COALESCE(SUM((SELECT COUNT(*) FROM jsonb_object_keys(sensor_values))), 0) AS values
            FROM {raw}
            WHERE source_chunk_index = :chunk_index
            """
        ),
        {"chunk_index": chunk.chunk_index},
    ).one()
    return int(counts.rows), int(counts.values)


def stage_backfill_chunk(
    session: Session,
    settings: Settings,
    record: UploadImport,
    state: UploadImportBackfill,
    chunk: UploadImportChunk,
    event: UploadFileEvent,
    measurement_path: Any,
    alias_to_sensorid: dict[str, int],
    station_timezone: str,
) -> tuple[int, int]:
    rows, values = _stage_rows(
        session,
        state,
        record,
        chunk,
        event,
        measurement_path,
        alias_to_sensorid,
        station_timezone,
        settings.BULK_IMPORT_STAGING_BATCH_SIZE,
    )
    state.staged_rows = int(
        session.execute(
            text(f"SELECT COUNT(*) FROM {_quote_identifier(state.raw_table_name)}")
        ).scalar_one()
    )
    state.staged_values = int(
        session.execute(
            text(
                "SELECT COALESCE(SUM((SELECT COUNT(*) FROM jsonb_object_keys(sensor_values))), 0) "
                f"FROM {_quote_identifier(state.raw_table_name)}"
            )
        ).scalar_one()
    )
    state.updated_at = datetime.now().astimezone()
    return rows, values


def materialize_and_validate(
    session: Session,
    settings: Settings,
    record: UploadImport,
    state: UploadImportBackfill,
) -> None:
    state = (
        session.query(UploadImportBackfill)
        .filter(UploadImportBackfill.import_id == record.id)
        .with_for_update()
        .one()
    )
    raw = _quote_identifier(state.raw_table_name)
    shadow = _quote_identifier(state.shadow_table_name)
    bucket_count = settings.BULK_BACKFILL_MATERIALIZE_BUCKETS
    bucket_predicate = _materialize_bucket_predicate(bucket_count)

    if state.phase == "staging":
        session.execute(text(f"TRUNCATE TABLE {shadow}"))
        state.materialize_cursor = 0
        state.phase = "materializing"
        state.updated_at = datetime.now().astimezone()
        session.commit()
    elif state.phase not in {"materializing", "validating"}:
        raise ValueError(f"Backfill is not ready to materialize: {state.phase}")

    if state.phase == "materializing":
        for bucket in range(state.materialize_cursor, bucket_count):
            session.execute(
                text(
                    f"""
                    WITH candidates AS (
                        SELECT raw.stationid, raw.collectiontime, raw.lat, raw.lon,
                               raw.source_chunk_index, raw.source_row_ordinal,
                               raw.upload_file_event_id,
                               sensor_value.key::INTEGER AS sensorid,
                               sensor_value.value::DOUBLE PRECISION AS measurementvalue
                        FROM {raw} AS raw
                        CROSS JOIN LATERAL jsonb_each_text(raw.sensor_values) AS sensor_value
                        WHERE {bucket_predicate}
                    ), first_source AS (
                        SELECT DISTINCT ON (sensorid, collectiontime)
                            stationid, collectiontime, lat, lon, source_chunk_index,
                            source_row_ordinal, upload_file_event_id, sensorid,
                            measurementvalue
                        FROM candidates
                        ORDER BY sensorid, collectiontime, source_chunk_index, source_row_ordinal
                    )
                    INSERT INTO {shadow}
                        (stationid, collectiontime, measurementvalue, geometry, sensorid,
                         variablename, upload_file_event_id)
                    SELECT first_source.stationid, first_source.collectiontime,
                           first_source.measurementvalue,
                           ST_SetSRID(ST_MakePoint(first_source.lon, first_source.lat), 4326),
                           first_source.sensorid, sensors.alias, first_source.upload_file_event_id
                    FROM first_source
                    LEFT JOIN sensors ON sensors.sensorid = first_source.sensorid
                    """
                ),
                {"bucket": bucket, "bucket_count": bucket_count},
            )
            state.materialize_cursor = bucket + 1
            state.updated_at = datetime.now().astimezone()
            session.commit()
            if record.worker_token:
                from app.services.upload_import_service import heartbeat

                heartbeat(session, settings, record.id, record.worker_token)
            state = (
                session.query(UploadImportBackfill)
                .filter(UploadImportBackfill.import_id == record.id)
                .one()
            )

    index_name = _quote_identifier(_shadow_index_name(state.shadow_table_name))
    session.execute(
        text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {shadow} (sensorid, collectiontime)"
        )
    )
    counts = session.execute(
        text(f"SELECT COUNT(*) AS rows, COALESCE(SUM(1), 0) AS values FROM {shadow}")
    ).one()
    invalid_sensors = session.execute(
        text(
            f"""
            SELECT COUNT(*) FROM {shadow} shadow
            LEFT JOIN sensors ON sensors.sensorid = shadow.sensorid
            WHERE sensors.sensorid IS NULL OR sensors.stationid <> :station_id
            """
        ),
        {"station_id": record.station_id},
    ).scalar_one()
    if int(invalid_sensors) != 0:
        raise ValueError("Backfill contains sensors that do not belong to the destination station")
    collisions = session.execute(
        text(
            f"""
            SELECT COUNT(*) FROM {shadow} shadow
            JOIN measurements live
              ON live.sensorid = shadow.sensorid
             AND live.collectiontime = shadow.collectiontime
            """
        )
    ).scalar_one()
    state.shadow_rows = int(counts.rows)
    state.shadow_values = int(counts.values)
    state.target_collisions = int(collisions)
    state.phase = "validating"
    state.updated_at = datetime.now().astimezone()
    session.commit()
    state.phase = "ready"
    state.validated_at = datetime.now().astimezone()
    state.updated_at = state.validated_at
    session.commit()
    # The validated shadow is now the durable recovery copy; release the raw
    # JSONB table before the live merge begins.
    session.execute(text(f"DROP TABLE IF EXISTS {raw}"))
    session.commit()


def merge_backfill(
    session: Session,
    settings: Settings,
    record: UploadImport,
    state: UploadImportBackfill,
) -> None:
    shadow = _quote_identifier(state.shadow_table_name)
    state = (
        session.query(UploadImportBackfill)
        .filter(UploadImportBackfill.import_id == record.id)
        .with_for_update()
        .one()
    )
    if state.phase == "ready":
        session.execute(text(f"DROP TABLE IF EXISTS {_quote_identifier(state.raw_table_name)}"))
        state.phase = "merging"
        state.lease_token = str(uuid4())
        state.lease_expires_at = datetime.now().astimezone() + timedelta(
            seconds=settings.BULK_IMPORT_WORKER_LEASE_SECONDS
        )
        state.updated_at = datetime.now().astimezone()
        session.commit()
    if state.phase not in {"merging", "merged"}:
        raise ValueError(f"Backfill is not ready to merge: {state.phase}")
    if state.phase == "merged":
        return

    while True:
        if record.worker_token:
            from app.services.upload_import_service import heartbeat

            heartbeat(session, settings, record.id, record.worker_token)
        state = (
            session.query(UploadImportBackfill)
            .filter(UploadImportBackfill.import_id == record.id)
            .with_for_update()
            .one()
        )
        if state.phase != "merging":
            raise ValueError(f"Backfill merge stopped in phase {state.phase}")
        _station_lock(session, record.station_id)
        page_max = session.execute(
            text(
                f"""
                SELECT MAX(shadow_row_id) FROM (
                    SELECT shadow_row_id FROM {shadow}
                    WHERE shadow_row_id > :cursor
                    ORDER BY shadow_row_id
                    LIMIT :batch_size
                ) page
                """
            ),
            {"cursor": state.merge_cursor, "batch_size": settings.BULK_BACKFILL_MERGE_BATCH_SIZE},
        ).scalar_one()
        if page_max is None:
            state.phase = "merged"
            state.merged_at = datetime.now().astimezone()
            state.lease_token = None
            state.lease_expires_at = None
            state.updated_at = datetime.now().astimezone()
            session.commit()
            return
        inserted = session.execute(
            text(
                f"""
                INSERT INTO measurements
                    (stationid, collectiontime, measurementvalue, geometry, sensorid,
                     variablename, upload_file_events_id)
                SELECT page.stationid, page.collectiontime, page.measurementvalue,
                       page.geometry, page.sensorid, page.variablename,
                       page.upload_file_event_id
                FROM {shadow} page
                WHERE page.shadow_row_id > :cursor
                  AND page.shadow_row_id <= :page_max
                ON CONFLICT (sensorid, collectiontime) DO NOTHING
                RETURNING measurementid
                """
            ),
            {"cursor": state.merge_cursor, "page_max": int(page_max)},
        ).scalars().all()
        state.merge_cursor = int(page_max)
        state.merged_values += len(inserted)
        state.lease_expires_at = datetime.now().astimezone() + timedelta(
            seconds=settings.BULK_IMPORT_WORKER_LEASE_SECONDS
        )
        state.updated_at = datetime.now().astimezone()
        session.commit()


def rollback_backfill(session: Session, record: UploadImport) -> int:
    state = (
        session.query(UploadImportBackfill)
        .filter(UploadImportBackfill.import_id == record.id)
        .with_for_update()
        .one_or_none()
    )
    if state is None:
        raise ValueError("Backfill state does not exist")
    if record.post_processing_status != "pending":
        raise ValueError("Backfill rollback is closed after post-processing starts")
    if state.phase not in {"ready", "merging", "merged"}:
        raise ValueError(f"Backfill cannot be rolled back from phase {state.phase}")
    _station_lock(session, record.station_id)
    delete_result = session.execute(
        text(
            """
            DELETE FROM measurements measurements
            USING upload_file_events events
            WHERE measurements.upload_file_events_id = events.id
              AND events.upload_session_id = :import_id
              AND events.station_id = :station_id
            """
        ),
        {"import_id": record.id, "station_id": record.station_id},
    )
    deleted = getattr(delete_result, "rowcount", 0)
    session.execute(text(f"DROP TABLE IF EXISTS {_quote_identifier(state.shadow_table_name)}"))
    session.execute(text(f"DROP TABLE IF EXISTS {_quote_identifier(state.raw_table_name)}"))
    state.phase = "rolled_back"
    state.rolled_back_at = datetime.now().astimezone()
    state.lease_token = None
    state.lease_expires_at = None
    state.updated_at = datetime.now().astimezone()
    record.status = "failed"
    record.last_error = "Import was explicitly rolled back"
    record.worker_token = None
    record.lease_expires_at = None
    record.updated_at = state.updated_at
    session.commit()
    return int(deleted or 0)


def cleanup_backfill_shadow(session: Session, record: UploadImport) -> None:
    state = (
        session.query(UploadImportBackfill)
        .filter(UploadImportBackfill.import_id == record.id)
        .one_or_none()
    )
    if state is None:
        return
    session.execute(text(f"DROP TABLE IF EXISTS {_quote_identifier(state.shadow_table_name)}"))
    session.execute(text(f"DROP TABLE IF EXISTS {_quote_identifier(state.raw_table_name)}"))
    state.updated_at = datetime.now().astimezone()
    session.commit()


def cleanup_backfill_tables(session: Session, record: UploadImport) -> None:
    state = (
        session.query(UploadImportBackfill)
        .filter(UploadImportBackfill.import_id == record.id)
        .one_or_none()
    )
    if state is None:
        return
    session.execute(text(f"DROP TABLE IF EXISTS {_quote_identifier(state.shadow_table_name)}"))
    session.execute(text(f"DROP TABLE IF EXISTS {_quote_identifier(state.raw_table_name)}"))
    state.phase = "failed"
    state.last_error = "Import processing failed after retry limit"
    state.updated_at = datetime.now().astimezone()
    session.commit()
