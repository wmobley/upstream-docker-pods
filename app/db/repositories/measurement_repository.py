from datetime import datetime
from typing import List, Optional, Tuple, Union

from pydantic import BaseModel
from sqlalchemy.orm import Session
from geoalchemy2 import WKTElement
from sqlalchemy import func, text
from app.api.v1.schemas.measurement import AggregatedMeasurement, MeasurementIn, MeasurementUpdate
from app.db.models.measurement import Measurement





class MeasurementRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_measurement(self, request: MeasurementIn, sensor_id: int) -> Measurement:
        # Convert the geometry string to WKTElement for PostGIS
        geometry = WKTElement(request.geometry, srid=4326)  # type: ignore[arg-type]

        db_measurement = Measurement(
            sensorid=sensor_id,
            variablename=request.variablename,
            collectiontime=request.collectiontime,
            variabletype=request.variabletype,
            description=request.description,
            measurementvalue=request.measurementvalue,
            geometry=geometry
        )
        self.db.add(db_measurement)
        self.db.commit()
        self.db.refresh(db_measurement)
        return db_measurement

    def get_measurement(self, measurement_id: int) -> Optional[Measurement]:
        return self.db.query(Measurement).get(measurement_id)

    def list_measurements(
        self,
        sensor_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        variable_name: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> Tuple[List[Tuple[Measurement, str]], int, Optional[float], Optional[float], Optional[float]]:
        query = self.db.query(Measurement, func.ST_AsGeoJSON(Measurement.geometry).label("geometry"))

        if sensor_id:
            query = query.filter(Measurement.sensorid == sensor_id)
        if start_date is not None:
            if isinstance(start_date, int):
                start_date = datetime.fromtimestamp(start_date)
            query = query.filter(Measurement.collectiontime >= start_date)
        if end_date is not None:
            if isinstance(end_date, int):
                end_date = datetime.fromtimestamp(end_date)
            query = query.filter(Measurement.collectiontime <= end_date)
        if min_value is not None:
            query = query.filter(Measurement.measurementvalue >= min_value)
        if max_value is not None:
            query = query.filter(Measurement.measurementvalue <= max_value)
        if variable_name:
            query = query.filter(Measurement.variablename == variable_name)

        # Order by collection time for time series data
        query = query.order_by(Measurement.collectiontime.desc())

        total_count = query.filter(Measurement.measurementvalue > 0).count()

        results_paginated = query.offset((page - 1) * limit).limit(limit).all()

        # Create a separate query for stats without ordering
        stats_query = self.db.query(Measurement)
        if sensor_id:
            stats_query = stats_query.filter(Measurement.sensorid == sensor_id)
        if start_date is not None:
            if isinstance(start_date, int):
                start_date = datetime.fromtimestamp(start_date)
            stats_query = stats_query.filter(Measurement.collectiontime >= start_date)
        if end_date is not None:
            if isinstance(end_date, int):
                end_date = datetime.fromtimestamp(end_date)
            stats_query = stats_query.filter(Measurement.collectiontime <= end_date)
        if min_value is not None:
            stats_query = stats_query.filter(Measurement.measurementvalue >= min_value)
        if max_value is not None:
            stats_query = stats_query.filter(Measurement.measurementvalue <= max_value)
        if variable_name:
            stats_query = stats_query.filter(Measurement.variablename == variable_name)

        stats_min_value = stats_query.with_entities(func.min(Measurement.measurementvalue)).scalar()
        stats_max_value = stats_query.with_entities(func.max(Measurement.measurementvalue)).scalar()
        stats_average_value = stats_query.with_entities(func.avg(Measurement.measurementvalue)).scalar()

        return results_paginated, total_count, stats_min_value, stats_max_value, stats_average_value

    def delete_measurement(self, measurement_id: int) -> bool:
        db_measurement = self.get_measurement(measurement_id)
        if db_measurement:
            self.db.delete(db_measurement)
            self.db.commit()
            return True
        return False

    def bulk_create_measurements(self, measurements: List[MeasurementIn], sensor_id: int) -> List[Measurement]:
        db_measurements = []
        for measurement in measurements:
            geometry = WKTElement(measurement.geometry, srid=4326)  # type: ignore[arg-type]
            db_measurement = Measurement(
                sensorid=sensor_id,
                variablename=measurement.variablename,
                collectiontime=measurement.collectiontime,
                variabletype=measurement.variabletype,
                description=measurement.description,
                measurementvalue=measurement.measurementvalue,
                geometry=geometry
            )
            self.db.add(db_measurement)
            db_measurements.append(db_measurement)

        self.db.commit()
        return db_measurements


    def get_measurements_with_confidence_intervals(
        self,
        sensor_id: int,
        interval: str = "hour",
        interval_value: int = 1,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None
    ) -> List[AggregatedMeasurement]:

        stmt = text("""
            SELECT * FROM get_sensor_aggregated_measurements(
                :sensor_id, :interval, :interval_value,
                :start_date, :end_date, :min_value, :max_value
            )
        """)
        result = self.db.execute(
            stmt,
            {
                "sensor_id": sensor_id,
                "interval": interval,
                "interval_value": interval_value,
                "start_date": start_date,
                "end_date": end_date,
                "min_value": min_value,
                "max_value": max_value
            }
        )
        # Process results - in SQLAlchemy v2, the rows are mappings by default
        measurements = [AggregatedMeasurement.model_validate(row) for row in result]

        return measurements



    def get_latest_measurement_by_sensor_id(self, sensor_id: int) -> Optional[Measurement]:
        return self.db.query(Measurement).filter(Measurement.sensorid == sensor_id).order_by(Measurement.collectiontime.desc()).first()
    
    
    def update_measurement(self, measurement_id: int, request:  MeasurementUpdate, partial: bool = False) -> Optional[Measurement]:
        
        db_measurement = self.db.query(Measurement).filter(Measurement.measurementid == measurement_id).first()
        
        if not db_measurement:
            return None
        

        if partial:
            # Get only the fields that were explicitly set in the request
            update_data = request.model_dump(exclude_unset=True)
            field_mapping = {
                'sensorid': 'sensorid', # This field is not updatable via this method
                'collectiontime': 'collectiontime',
                'geometry': 'geometry',
                'measurementvalue': 'measurementvalue',
                'variabletype': 'variabletype',
                'description': 'description',
            }
            for field, value in update_data.items():
                db_field = field_mapping.get(field, field)
                if db_field == 'geometry' and value is not None:
                    setattr(db_measurement, db_field, WKTElement(value, srid=4326))
                else:
                    setattr(db_measurement, db_field, value)
        else:
            # Full update (existing logic)
            # Ensure all fields for a full update are provided and not None
            sensorid = request.sensorid
            collectiontime = request.collectiontime
            geometry = request.geometry
            measurementvalue = request.measurementvalue
            variabletype = request.variabletype
            

            if sensorid is None:
                raise ValueError("Sensor ID must be provided for a full update")
            if collectiontime is None:
                raise ValueError("collectiontime must be provided for a full update")
            if geometry is None:
                raise ValueError("geometry must be provided for a full update")
            if measurementvalue is None:
                raise ValueError("measurementvalue must be provided for a full update")
            if variabletype is None:
                raise ValueError("variabletype must be provided for a full update")
            
            db_measurement.sensorid = sensorid
            db_measurement.collectiontime = collectiontime
            db_measurement.geometry = WKTElement(geometry, srid=4326)  # type: ignore[assignment]
            db_measurement.measurementvalue = measurementvalue
            db_measurement.variabletype = variabletype
            
            
        self.db.commit()
        self.db.refresh(db_measurement)
        return db_measurement