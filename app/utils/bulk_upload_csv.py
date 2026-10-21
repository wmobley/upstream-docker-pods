"""Opt-in, set-based CSV measurement ingestion experiment.

This module deliberately stays separate from the legacy pandas importer.  It
keeps only a bounded batch of parsed CSV rows in Python, stages their sensor
values as JSONB, and lets PostgreSQL perform the wide-to-long expansion and
duplicate-safe insert.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy import Float, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.utils.timezone import localize_collectiontime


STAGING_BATCH_SIZE = 100


@dataclass
class BulkMeasurementsProcessingResult:
    """Audit counts returned by the bulk experiment."""

    rows_read: int = 0
    values_attempted: int = 0
    values_inserted: int = 0
    errors: list[str] = field(default_factory=list)
    per_alias: dict[str, int] = field(default_factory=dict)

    @property
    def values_skipped_duplicate(self) -> int:
        return max(self.values_attempted - self.values_inserted, 0)


BULK_INSERT_SQL = text(
    """
    WITH candidates AS (
        SELECT
            stage.stationid,
            stage.collectiontime,
            stage.source_row_ordinal,
            sensor_value.key::INTEGER AS sensorid,
            sensor_value.value::DOUBLE PRECISION AS measurementvalue,
            stage.geometry
        FROM upload_measurement_bulk_stage AS stage
        CROSS JOIN LATERAL jsonb_each_text(stage.sensor_values) AS sensor_value
    ), first_source AS (
        SELECT DISTINCT ON (sensorid, collectiontime)
            stationid,
            collectiontime,
            source_row_ordinal,
            sensorid,
            measurementvalue,
            geometry
        FROM candidates
        ORDER BY sensorid, collectiontime, source_row_ordinal
    ), inserted AS (
        INSERT INTO measurements (
            stationid,
            collectiontime,
            measurementvalue,
            geometry,
            sensorid,
            variablename,
            upload_file_events_id
        )
        SELECT
            first_source.stationid,
            first_source.collectiontime,
            first_source.measurementvalue,
            first_source.geometry,
            first_source.sensorid,
            sensors.alias,
            :upload_event_id
        FROM first_source
        JOIN sensors ON sensors.sensorid = first_source.sensorid
        ON CONFLICT (sensorid, collectiontime) DO NOTHING
        RETURNING measurementid
    )
    SELECT
        (SELECT COUNT(*) FROM candidates) AS values_attempted,
        (SELECT COUNT(*) FROM inserted) AS values_inserted
    """
)

STAGE_TABLE_SQL = text(
    """
    CREATE TEMPORARY TABLE IF NOT EXISTS upload_measurement_bulk_stage (
        source_row_ordinal BIGINT NOT NULL,
        stationid INTEGER NOT NULL,
        collectiontime TIMESTAMPTZ NOT NULL,
        lat DOUBLE PRECISION NOT NULL,
        lon DOUBLE PRECISION NOT NULL,
        geometry geometry(POINT, 4326) NOT NULL,
        sensor_values JSONB NOT NULL
    ) ON COMMIT DELETE ROWS
    """
)


def _parse_stage_row(
    row: dict[str, str | None],
    *,
    source_row_ordinal: int,
    station_id: int,
    alias_to_sensorid_map: dict[str, int],
    station_timezone: str,
    per_alias: dict[str, int],
) -> dict[str, Any]:
    """Convert one CSV row into a compact JSONB staging record."""
    try:
        collectiontime = localize_collectiontime(
            row.get("collectiontime") or "", station_timezone
        )
        if not isinstance(collectiontime, datetime):
            raise ValueError("collectiontime is not a datetime")
        # Validate coordinates before PostgreSQL's set-based cast so malformed
        # rows produce a useful client error rather than a generic SQL failure.
        lat = row.get("Lat_deg") or ""
        lon = row.get("Lon_deg") or ""
        float(lat)
        float(lon)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid measurement row {source_row_ordinal}: {exc}",
        ) from exc

    sensor_values: dict[str, float] = {}
    for alias, sensor_id in alias_to_sensorid_map.items():
        value = row.get(alias)
        if value is None or value == "":
            continue
        try:
            sensor_values[str(sensor_id)] = float(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid value for sensor '{alias}' on measurement row "
                    f"{source_row_ordinal}: {value}"
                ),
            ) from exc
        per_alias[alias] = per_alias.get(alias, 0) + 1

    return {
        "source_row_ordinal": source_row_ordinal,
        "stationid": station_id,
        "collectiontime": collectiontime,
        "lat": lat,
        "lon": lon,
        "sensor_values": sensor_values,
    }


def _flush_stage_batch(
    session: Session,
    stage_insert: Any,
    stage_batch: list[dict[str, Any]],
    upload_event_id: int,
    station_lock_callback: Any = None,
) -> tuple[int, int]:
    """Insert and process one bounded stage batch, then commit it."""
    if not stage_batch:
        return 0, 0
    if station_lock_callback is not None:
        station_lock_callback()
    # Session commits may return the connection to the pool. Recreate the
    # connection-local temporary table before every batch so a later batch
    # cannot land on a connection where the table has not been created.
    session.execute(STAGE_TABLE_SQL)
    session.execute(stage_insert, stage_batch)
    counts = session.execute(
        BULK_INSERT_SQL,
        {"upload_event_id": upload_event_id},
    ).one()
    attempted = int(counts.values_attempted)
    inserted = int(counts.values_inserted)
    session.commit()
    return attempted, inserted


def process_measurements_file_bulk(
    file: UploadFile,
    station_id: int,
    alias_to_sensorid_map: dict[str, int],
    upload_event_id: int,
    session: Session,
    station_timezone: str | None = None,
    staging_batch_size: int = STAGING_BATCH_SIZE,
    station_lock_callback: Any = None,
) -> BulkMeasurementsProcessingResult:
    """Process one bounded upload chunk with JSONB staging and SQL unpivoting.

    The temporary table is scoped to the current database connection and is
    cleared on each bounded commit. It is therefore safe for concurrent
    imports and leaves no staging rows behind when the request completes.
    """
    if not alias_to_sensorid_map:
        return BulkMeasurementsProcessingResult()
    if staging_batch_size <= 0:
        raise ValueError("staging_batch_size must be positive")

    timezone = station_timezone or "UTC"
    text_stream = io.TextIOWrapper(file.file, encoding="utf-8-sig", newline="")
    reader = csv.DictReader(text_stream)
    fieldnames = reader.fieldnames or []
    required_columns = {"collectiontime", "Lat_deg", "Lon_deg"}
    missing_required = sorted(required_columns - set(fieldnames))
    if missing_required:
        raise HTTPException(
            status_code=400,
            detail=f"Measurements CSV is missing required column(s): {missing_required}",
        )

    missing_aliases = [alias for alias in alias_to_sensorid_map if alias not in fieldnames]
    errors = [
        f"Measurements columns are {fieldnames} doesn't match with '{alias}'"
        for alias in missing_aliases
    ]
    usable_aliases = {
        alias: sensor_id
        for alias, sensor_id in alias_to_sensorid_map.items()
        if alias in fieldnames
    }
    if not usable_aliases:
        return BulkMeasurementsProcessingResult(errors=errors)

    session.execute(STAGE_TABLE_SQL)
    stage_insert = text(
        """
        INSERT INTO upload_measurement_bulk_stage
            (source_row_ordinal, stationid, collectiontime, lat, lon, geometry, sensor_values)
        VALUES
            (
                :source_row_ordinal,
                :stationid,
                :collectiontime,
                :lat,
                :lon,
                ST_SetSRID(
                    ST_MakePoint(:lon, :lat),
                    4326
                ),
                :sensor_values
            )
        """
    ).bindparams(
        bindparam("lat", type_=Float),
        bindparam("lon", type_=Float),
        bindparam("sensor_values", type_=JSONB),
    )

    result = BulkMeasurementsProcessingResult(errors=errors)
    stage_batch: list[dict[str, Any]] = []
    for source_row_ordinal, row in enumerate(reader):
        result.rows_read += 1
        stage_batch.append(
            _parse_stage_row(
                row,
                source_row_ordinal=source_row_ordinal,
                station_id=station_id,
                alias_to_sensorid_map=usable_aliases,
                station_timezone=timezone,
                per_alias=result.per_alias,
            )
        )
        if len(stage_batch) >= staging_batch_size:
            attempted, inserted = _flush_stage_batch(
                session,
                stage_insert,
                stage_batch,
                upload_event_id,
                station_lock_callback,
            )
            result.values_attempted += attempted
            result.values_inserted += inserted
            stage_batch.clear()

    if stage_batch:
        attempted, inserted = _flush_stage_batch(
            session,
            stage_insert,
            stage_batch,
            upload_event_id,
            station_lock_callback,
        )
        result.values_attempted += attempted
        result.values_inserted += inserted
    else:
        session.commit()

    return result
