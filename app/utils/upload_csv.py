from datetime import datetime
import logging
import pandas as pd
from sqlalchemy import insert
from sqlalchemy.dialects.postgresql import insert
from starlette.formparsers import MultiPartParser
from fastapi import HTTPException, UploadFile
from pandantic import BaseModel as PandanticBaseModel
from geoalchemy2 import WKTElement
from sqlalchemy.orm import Session
from app.db.models.measurement import Measurement
from app.db.repositories.sensor_repository import SensorRepository
from app.db.models.sensor import Sensor
from app.api.v1.schemas.sensor import SensorIn

from typing import Dict, List, Union
# Constants
MultiPartParser.spool_max_size = 500 * 1024 * 1024
BATCH_SIZE = 10000
DEFAULT_VARIABLE_NAME = 'No BestGuess Formula'


def process_batch(batch: List[Dict[str, Union[int, datetime, float, WKTElement]]], session: Session) -> int:
    """Process a batch of measurements and insert to database."""
    if not batch:
        return 0
    stmt = insert(Measurement).values(batch)
    stmt = stmt.on_conflict_do_nothing( # type: ignore[attr-defined]
        index_elements=['sensorid', 'collectiontime']
    )
    result = session.execute(stmt)
    inserted_count = result.rowcount if hasattr(result, 'rowcount') else len(batch)
    session.commit()
    batch.clear()
    return inserted_count

def process_sensors_file(file: UploadFile, station_id: int, upload_event_id: int, session: Session) -> Dict[str, int]:
    """Process the sensors CSV file and return a mapping of aliases to sensor IDs."""
    # Read CSV using pandas
    sensor_repository = SensorRepository(session)
    df_sensors = pd.read_csv(file.file, keep_default_na=False, na_values=[])
    sensor_maps : List[Sensor]= []
    existing_sensors : List[Sensor]= []
    validator = PandanticBaseModel(schema=SensorIn)

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
            variablename=sensor_row.variablename if 'variablename' in sensor_row else DEFAULT_VARIABLE_NAME,
            stationid=station_id,
            upload_file_events_id=upload_event_id,
            units=sensor_row.units if 'units' in sensor_row else None,
            postprocess=sensor_row.postprocess if 'postprocess' in sensor_row else None,
            postprocessscript=sensor_row.postprocessscript if 'postprocessscript' in sensor_row else None,
        )
        existing_sensor = sensor_repository.get_sensor_by_alias_and_station_id(str(sensor.alias), station_id)
        if existing_sensor is None:
            sensor_maps.append(sensor)
        else:
            existing_sensors.append(existing_sensor)
    sensor_repository.create_sensors(sensor_maps)

    # Get sensor mapping
    alias_to_sensorid = session.query(
        Sensor.alias, Sensor.sensorid
    ).filter(Sensor.upload_file_events_id == upload_event_id).all()

    response: Dict[str, int] = {}
    for el in alias_to_sensorid:
        if el.alias is not None:
          response[el.alias] = el.sensorid
    for sensor in existing_sensors:
        if sensor.alias is not None:
          response[sensor.alias] = sensor.sensorid

    return response

def create_measurement_dict(
    station_id: int,
    collection_time: datetime,
    measurement_value: float,
    geometry: WKTElement,
    sensor_id: int,
    upload_event_id: int
) -> Dict[str, Union[int, datetime, float, WKTElement]]:
    """Create a measurement dictionary with all required fields."""
    return {
        'stationid': station_id,
        'collectiontime': collection_time,
        'measurementvalue': measurement_value,
        'geometry': geometry,
        'sensorid': sensor_id,
        'upload_file_events_id': upload_event_id
    }

def process_measurements_file(
    file: UploadFile,
    station_id: int,
    alias_to_sensorid_map: Dict[str, int],
    upload_event_id: int,
    session: Session
) -> tuple[int, list[str]]:
    """Process the measurements CSV file and return total number of measurements processed and any errors."""
    # Read CSV using pandas

    df = pd.read_csv(
        file.file,
        keep_default_na=False,  # Prevent NaN creation
        na_values=[''],         # Only empty strings become NaN
        dtype={'Lon_deg': 'str', 'Lat_deg': 'str'},  # Pre-specify dtypes
    )
    measurement_batch = []
    total_measurements = 0
    errors = []
    df['geometry_str'] = 'Point (' + df['Lon_deg'] + ' ' + df['Lat_deg'] + ')'

    for alias, sensor_id in alias_to_sensorid_map.items():
        if alias not in df.columns:
            # Handle errors if alias is missing in the file
            error_msg = f"Measurements columns are {df.columns.tolist()} doesn't match with '{alias}'"
            logging.error(error_msg)
            errors.append(error_msg)
            continue
        valid_mask = pd.notna(df[alias])
        if not valid_mask.any():
            continue

        sensor_measurements = [
            {
                'stationid': station_id,
                'collectiontime': time,
                'measurementvalue': value,
                'geometry': WKTElement(geom, srid=4326),
                'sensorid': sensor_id,
                'variablename': alias,
                'upload_file_events_id': upload_event_id
            }
            for time, value, geom in zip(
                df.loc[valid_mask, 'collectiontime'],
                df.loc[valid_mask, alias],
                df.loc[valid_mask, 'geometry_str']
            )
        ]
        measurement_batch.extend(sensor_measurements)
        if len(measurement_batch) >= BATCH_SIZE:
            total_measurements += process_batch(measurement_batch, session)
            measurement_batch = []

    if measurement_batch:
        total_measurements += process_batch(measurement_batch, session)
        measurement_batch = []

    return total_measurements, errors

def update_sensor_statistics(sensor_repository: SensorRepository, alias_to_sensorid_map: Dict[str, int]) -> None:
    """Update statistics for all sensors."""
    for sensor_id in alias_to_sensorid_map.values():
        sensor_repository.delete_sensor_statistics(sensor_id)
        sensor_repository.refresh_sensor_statistics(sensor_id)