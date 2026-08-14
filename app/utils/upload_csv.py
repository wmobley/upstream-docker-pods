import logging
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
from fastapi import HTTPException, UploadFile
from geoalchemy2 import WKTElement
from pandantic import Pandantic
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from starlette.formparsers import MultiPartParser

from app.api.v1.schemas.sensor import SensorIn
from app.db.models.measurement import Measurement
from app.db.models.sensor import Sensor
from app.db.repositories.sensor_repository import SensorRepository

# Constants
MultiPartParser.spool_max_size = 500 * 1024 * 1024
# Keep each INSERT safely below PostgreSQL's 65535 bind-parameter limit.
# Each measurement row binds 7 values in the bulk insert statement.
POSTGRES_MAX_BIND_PARAMS = 65535
MEASUREMENT_INSERT_PARAM_COUNT = 7
BATCH_SIZE = 9000
DEFAULT_VARIABLE_NAME = "No BestGuess Formula"
logger = logging.getLogger(__name__)


MeasurementValue = int | datetime | float | str | WKTElement


@dataclass
class BatchInsertResult:
    """Result of inserting one batch of candidate measurement values.

    ``values_attempted`` is the number of candidate rows sent to the insert
    statement. ``values_inserted`` is the number of rows actually inserted
    (via SQLAlchemy ``rowcount``). The difference is rows skipped by
    ``ON CONFLICT DO NOTHING`` on ``(sensorid, collectiontime)``.
    """

    values_attempted: int = 0
    values_inserted: int = 0

    @property
    def values_skipped_duplicate(self) -> int:
        return max(self.values_attempted - self.values_inserted, 0)


@dataclass
class MeasurementsProcessingResult:
    """Structured result of processing a measurements CSV upload.

    ``rows_read`` counts CSV data rows after the header (including rows where
    all sensor alias values are blank). ``values_attempted`` counts only
    non-blank values in known alias columns that were sent to the insert path.
    ``values_inserted`` is the count of rows actually inserted. The duplicate
    skip count is derived as ``values_attempted - values_inserted`` because the
    only ignored insert path is ``ON CONFLICT DO NOTHING`` on
    ``(sensorid, collectiontime)``.
    """

    rows_read: int = 0
    values_attempted: int = 0
    values_inserted: int = 0
    errors: list[str] = field(default_factory=list)
    per_alias: dict[str, int] = field(default_factory=dict)

    @property
    def values_skipped_duplicate(self) -> int:
        return max(self.values_attempted - self.values_inserted, 0)


def process_batch(
    batch: list[dict[str, MeasurementValue]], session: Session
) -> BatchInsertResult:
    """Process a batch of measurements and insert to database."""
    if not batch:
        return BatchInsertResult(values_attempted=0, values_inserted=0)
    stmt = insert(Measurement).values(batch)
    stmt = stmt.on_conflict_do_nothing(index_elements=["sensorid", "collectiontime"])
    result = session.execute(stmt)
    inserted_count = result.rowcount if hasattr(result, "rowcount") else len(batch)
    session.commit()
    batch_result = BatchInsertResult(
        values_attempted=len(batch),
        values_inserted=int(inserted_count) if inserted_count is not None else 0,
    )
    logger.info(
        "upload_csv_process_batch extra=%s",
        {
            "batch_size": len(batch),
            "values_attempted": batch_result.values_attempted,
            "values_inserted": batch_result.values_inserted,
            "values_skipped_duplicate": batch_result.values_skipped_duplicate,
        },
    )
    batch.clear()
    return batch_result


def _is_empty_upload(file: UploadFile) -> bool:
    """Return True when the uploaded file has no content.

    The upload UI sends an empty placeholder CSV when the user only provides
    one of the two files (sensors or measurements); pandas' read_csv raises
    EmptyDataError on a 0-byte stream, so callers should treat that as "no
    rows" instead of letting it crash the request.
    """
    position = file.file.tell()
    file.file.seek(0, 2)
    is_empty = file.file.tell() == 0
    file.file.seek(position)
    return is_empty


def process_sensors_file(
    file: UploadFile, station_id: int, upload_event_id: int, session: Session
) -> dict[str, int]:
    """Process the sensors CSV file and return a mapping of aliases to sensor IDs."""
    if _is_empty_upload(file):
        logger.info(
            "process_sensors_file_empty_upload extra=%s",
            {"station_id": station_id, "upload_event_id": upload_event_id, "filename": file.filename},
        )
        return {}

    # Read CSV using pandas
    sensor_repository = SensorRepository(session)
    df_sensors = pd.read_csv(file.file, keep_default_na=False, na_values=[])
    logger.info(
        "process_sensors_file_read extra=%s",
        {
            "station_id": station_id,
            "upload_event_id": upload_event_id,
            "filename": file.filename,
            "row_count": len(df_sensors.index),
            "columns": df_sensors.columns.tolist(),
        },
    )
    sensor_maps: list[Sensor] = []
    existing_sensors: list[Sensor] = []
    validator = Pandantic(schema=SensorIn)

    try:
        validator.validate(dataframe=df_sensors, errors="raise")
    except ValueError as e:
        file.file.close()
        logging.error(f"Validation error: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Validation failed: {str(e)}")
    # Process each row
    for _, sensor_row in df_sensors.iterrows():
        sensor: Sensor = Sensor(
            alias=sensor_row.alias,
            variablename=(
                sensor_row.variablename
                if "variablename" in sensor_row
                else DEFAULT_VARIABLE_NAME
            ),
            stationid=station_id,
            upload_file_events_id=upload_event_id,
            units=sensor_row.units if "units" in sensor_row else None,
            postprocess=sensor_row.postprocess if "postprocess" in sensor_row else None,
            postprocessscript=(
                sensor_row.postprocessscript
                if "postprocessscript" in sensor_row
                else None
            ),
        )
        existing_sensor = sensor_repository.get_sensor_by_alias_and_station_id(
            str(sensor.alias), station_id
        )
        if existing_sensor is None:
            sensor_maps.append(sensor)
        else:
            existing_sensors.append(existing_sensor)
    logger.info(
        "process_sensors_file_classified extra=%s",
        {
            "station_id": station_id,
            "upload_event_id": upload_event_id,
            "new_sensor_count": len(sensor_maps),
            "existing_sensor_count": len(existing_sensors),
            "aliases": [str(sensor.alias) for sensor in sensor_maps],
        },
    )
    sensor_repository.create_sensors(sensor_maps)

    # Get sensor mapping
    alias_to_sensorid = (
        session.query(Sensor.alias, Sensor.sensorid)
        .filter(Sensor.upload_file_events_id == upload_event_id)
        .all()
    )

    response: dict[str, int] = {}
    for el in alias_to_sensorid:
        if el.alias is not None:
            response[el.alias] = el.sensorid
    for sensor in existing_sensors:
        if sensor.alias is not None:
            response[sensor.alias] = sensor.sensorid

    logger.info(
        "process_sensors_file_done extra=%s",
        {
            "station_id": station_id,
            "upload_event_id": upload_event_id,
            "alias_to_sensorid_map": response,
        },
    )

    return response


def create_measurement_dict(
    station_id: int,
    collection_time: datetime,
    measurement_value: float,
    geometry: WKTElement,
    sensor_id: int,
    upload_event_id: int,
) -> dict[str, MeasurementValue]:
    """Create a measurement dictionary with all required fields."""
    return {
        "stationid": station_id,
        "collectiontime": collection_time,
        "measurementvalue": measurement_value,
        "geometry": geometry,
        "sensorid": sensor_id,
        "upload_file_events_id": upload_event_id,
    }


def process_measurements_file(
    file: UploadFile,
    station_id: int,
    alias_to_sensorid_map: dict[str, int],
    upload_event_id: int,
    session: Session,
) -> MeasurementsProcessingResult:
    """Process the measurements CSV file and return a structured result.

    The returned ``MeasurementsProcessingResult`` reports CSV rows read, the
    number of candidate measurement values attempted, the number actually
    inserted, and any row/schema errors encountered.
    """
    if _is_empty_upload(file):
        logger.info(
            "process_measurements_file_empty_upload extra=%s",
            {"station_id": station_id, "upload_event_id": upload_event_id, "filename": file.filename},
        )
        return MeasurementsProcessingResult(rows_read=0)

    # Read CSV using pandas
    try:
        df = pd.read_csv(
            file.file,
            keep_default_na=False,  # Prevent NaN creation
            na_values=[""],  # Only empty strings become NaN
            dtype={"Lon_deg": "str", "Lat_deg": "str"},  # Pre-specify dtypes
        )
    except pd.errors.EmptyDataError:
        # Sensors-only uploads send an empty measurements blob; treat it as
        # zero measurement rows rather than a 500.
        logger.info(
            "process_measurements_file_empty_blob extra=%s",
            {
                "station_id": station_id,
                "upload_event_id": upload_event_id,
                "filename": file.filename,
            },
        )
        return MeasurementsProcessingResult(rows_read=0)
    logger.info(
        "process_measurements_file_read extra=%s",
        {
            "station_id": station_id,
            "upload_event_id": upload_event_id,
            "filename": file.filename,
            "row_count": len(df.index),
            "columns": df.columns.tolist(),
            "alias_count": len(alias_to_sensorid_map),
            "aliases": sorted(alias_to_sensorid_map.keys()),
        },
    )
    max_rows_per_insert = min(
        BATCH_SIZE, POSTGRES_MAX_BIND_PARAMS // MEASUREMENT_INSERT_PARAM_COUNT
    )
    measurement_batch: list[dict[str, MeasurementValue]] = []
    result = MeasurementsProcessingResult(rows_read=len(df.index))
    errors = []
    lon_series = df["Lon_deg"].astype(str)
    lat_series = df["Lat_deg"].astype(str)
    combined_coords = lon_series.str.cat(lat_series, sep=" ")
    df["geometry_str"] = combined_coords.map(lambda coords: f"Point ({coords})")

    for alias, sensor_id in alias_to_sensorid_map.items():
        if alias not in df.columns:
            # Handle errors if alias is missing in the file
            error_msg = f"Measurements columns are {df.columns.tolist()} doesn't match with '{alias}'"
            logger.error(error_msg)
            errors.append(error_msg)
            continue
        valid_mask = pd.notna(df[alias])
        if not valid_mask.any():
            logger.info(
                "process_measurements_file_no_values_for_alias extra=%s",
                {
                    "station_id": station_id,
                    "upload_event_id": upload_event_id,
                    "alias": alias,
                    "sensor_id": sensor_id,
                },
            )
            result.per_alias[alias] = 0
            continue

        alias_value_count = int(valid_mask.sum())
        result.per_alias[alias] = alias_value_count
        logger.info(
            "process_measurements_file_alias_values extra=%s",
            {
                "station_id": station_id,
                "upload_event_id": upload_event_id,
                "alias": alias,
                "sensor_id": sensor_id,
                "value_count": alias_value_count,
            },
        )
        for time, value, geom in zip(
            df.loc[valid_mask, "collectiontime"],
            df.loc[valid_mask, alias],
            df.loc[valid_mask, "geometry_str"],
        ):
            measurement_batch.append(
                {
                    "stationid": station_id,
                    "collectiontime": time,
                    "measurementvalue": value,
                    "geometry": WKTElement(geom, srid=4326),
                    "sensorid": sensor_id,
                    "variablename": alias,
                    "upload_file_events_id": upload_event_id,
                }
            )
            result.values_attempted += 1
            if len(measurement_batch) >= max_rows_per_insert:
                batch_result = process_batch(measurement_batch, session)
                result.values_inserted += batch_result.values_inserted
                measurement_batch = []

    if measurement_batch:
        batch_result = process_batch(measurement_batch, session)
        result.values_inserted += batch_result.values_inserted
        measurement_batch = []

    result.errors = errors

    # per_alias maps each alias to the number of non-blank values attempted.
    # Exact per-alias inserted/skipped counts are not tracked because batches
    # interleave multiple aliases; the aggregate values are authoritative.
    logger.info(
        "process_measurements_file_done extra=%s",
        {
            "station_id": station_id,
            "upload_event_id": upload_event_id,
            "max_rows_per_insert": max_rows_per_insert,
            "rows_read": result.rows_read,
            "values_attempted": result.values_attempted,
            "values_inserted": result.values_inserted,
            "values_skipped_duplicate": result.values_skipped_duplicate,
            "error_count": len(errors),
            "errors": errors,
        },
    )

    return result


def update_sensor_statistics(
    sensor_repository: SensorRepository, alias_to_sensorid_map: dict[str, int]
) -> None:
    """Update statistics for all sensors."""
    for sensor_id in alias_to_sensorid_map.values():
        logger.info(
            "update_sensor_statistics_sensor_start extra=%s",
            {"sensor_id": sensor_id},
        )
        sensor_repository.delete_sensor_statistics(sensor_id)
        sensor_repository.refresh_sensor_statistics(sensor_id)
        logger.info(
            "update_sensor_statistics_sensor_done extra=%s",
            {"sensor_id": sensor_id},
        )
