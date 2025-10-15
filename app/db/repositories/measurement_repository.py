from datetime import datetime
from typing import List
import typing

from sqlalchemy.orm import Session
from geoalchemy2 import WKTElement
from sqlalchemy import func, text, select
from app.api.v1.schemas.measurement import (
    AggregatedMeasurement,
    MeasurementIn,
    MeasurementUpdate,
)
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
            geometry=geometry,
        )
        self.db.add(db_measurement)
        self.db.commit()
        self.db.refresh(db_measurement)
        return db_measurement

    def get_measurement(self, measurement_id: int) -> Measurement | None:
        return self.db.query(Measurement).get(measurement_id)

    def list_measurements(
        self,
        sensor_id: int | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        variable_name: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[
        list[tuple[Measurement, str]], int, float | None, float | None, float | None
    ]:
        query = self.db.query(
            Measurement, func.ST_AsGeoJSON(Measurement.geometry).label("geometry")
        )

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

        stats_min_value = stats_query.with_entities(
            func.min(Measurement.measurementvalue)
        ).scalar()
        stats_max_value = stats_query.with_entities(
            func.max(Measurement.measurementvalue)
        ).scalar()
        stats_average_value = stats_query.with_entities(
            func.avg(Measurement.measurementvalue)
        ).scalar()

        return (
            results_paginated,
            total_count,
            stats_min_value,
            stats_max_value,
            stats_average_value,
        )

    def delete_measurement(self, measurement_id: int) -> bool:
        db_measurement = self.get_measurement(measurement_id)
        if db_measurement:
            self.db.delete(db_measurement)
            self.db.commit()
            return True
        return False

    def bulk_create_measurements(
        self, measurements: List[MeasurementIn], sensor_id: int
    ) -> List[Measurement]:
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
                geometry=geometry,
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
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
    ) -> List[AggregatedMeasurement]:

        stmt = text(
            """
            SELECT * FROM get_sensor_aggregated_measurements(
                :sensor_id, :interval, :interval_value,
                :start_date, :end_date, :min_value, :max_value
            )
        """
        )
        result = self.db.execute(
            stmt,
            {
                "sensor_id": sensor_id,
                "interval": interval,
                "interval_value": interval_value,
                "start_date": start_date,
                "end_date": end_date,
                "min_value": min_value,
                "max_value": max_value,
            },
        )
        # Process results - in SQLAlchemy v2, the rows are mappings by default
        measurements = [AggregatedMeasurement.model_validate(row) for row in result]

        return measurements

    def get_latest_measurement_by_sensor_id(self, sensor_id: int) -> Measurement | None:
        return (
            self.db.query(Measurement)
            .filter(Measurement.sensorid == sensor_id)
            .order_by(Measurement.collectiontime.desc())
            .first()
        )

    def update_measurement(
        self, measurement_id: int, request: MeasurementUpdate, partial: bool = False
    ) -> Measurement | None:

        db_measurement = (
            self.db.query(Measurement)
            .filter(Measurement.measurementid == measurement_id)
            .first()
        )

        if not db_measurement:
            return None

        if partial:
            # Get only the fields that were explicitly set in the request
            update_data = request.model_dump(exclude_unset=True)
            field_mapping = {
                "sensorid": "sensorid",  # This field is not updatable via this method
                "collectiontime": "collectiontime",
                "geometry": "geometry",
                "measurementvalue": "measurementvalue",
                "variabletype": "variabletype",
                "description": "description",
            }
            for field, value in update_data.items():
                db_field = field_mapping.get(field, field)
                if db_field == "geometry" and value is not None:
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

    def get_measurements_by_campaign_chunked(
        self,
        campaign_id: int,
        chunk_size: int = 1000,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> "typing.Iterator[List[typing.Tuple[Measurement, str]]]":
        """Generator that yields measurements for a campaign in chunks."""
        from app.db.models.sensor import Sensor
        from app.db.models.station import Station

        offset = 0
        while True:
            stmt = (
                select(Measurement, Sensor.alias)
                .join(Sensor, Measurement.sensorid == Sensor.sensorid)
                .join(Station, Sensor.stationid == Station.stationid)
                .filter(Station.campaignid == campaign_id)
                .order_by(Measurement.collectiontime, Measurement.measurementid)
                .offset(offset)
                .limit(chunk_size)
            )

            if start_date:
                stmt = stmt.filter(Measurement.collectiontime >= start_date)
            if end_date:
                stmt = stmt.filter(Measurement.collectiontime <= end_date)

            result = list(self.db.execute(stmt).all())
            if not result:
                break

            # Convert Row objects to tuples and filter out None aliases
            filtered_result = []
            for row in result:
                measurement, alias = row
                if alias is not None:
                    filtered_result.append((measurement, alias))

            if filtered_result:
                yield filtered_result
            offset += chunk_size

    def get_unique_sensor_aliases_for_campaign(self, campaign_id: int) -> List[str]:
        """Get unique sensor aliases for a campaign to construct CSV headers."""
        from app.db.models.sensor import Sensor
        from app.db.models.station import Station

        stmt = (
            select(Sensor.alias)
            .join(Station, Sensor.stationid == Station.stationid)
            .filter(Station.campaignid == campaign_id)
            .filter(Sensor.alias.is_not(None))
            .distinct()
            .order_by(Sensor.alias)
        )

        result = self.db.execute(stmt).scalars().all()
        return [alias for alias in result if alias is not None]

    def get_unique_sensor_aliases_for_station(self, station_id: int) -> List[str]:
        """Get unique sensor aliases for a station to construct CSV headers."""
        from app.db.models.sensor import Sensor

        stmt = (
            select(Sensor.alias)
            .filter(Sensor.stationid == station_id)
            .filter(Sensor.alias.is_not(None))
            .distinct()
            .order_by(Sensor.alias)
        )

        result = self.db.execute(stmt).scalars().all()
        return [alias for alias in result if alias is not None]

    def get_measurements_by_station_chunked(
        self,
        station_id: int,
        chunk_size: int = 1000,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> "typing.Iterator[List[typing.Tuple[Measurement, str]]]":
        """Generator that yields measurements for a station in chunks."""
        from app.db.models.sensor import Sensor

        offset = 0
        while True:
            stmt = (
                select(Measurement, Sensor.alias)
                .join(Sensor, Measurement.sensorid == Sensor.sensorid)
                .filter(Sensor.stationid == station_id)
                .order_by(Measurement.collectiontime, Measurement.measurementid)
                .offset(offset)
                .limit(chunk_size)
            )

            if start_date:
                stmt = stmt.filter(Measurement.collectiontime >= start_date)
            if end_date:
                stmt = stmt.filter(Measurement.collectiontime <= end_date)

            result = list(self.db.execute(stmt).all())
            if not result:
                break

            # Convert Row objects to tuples and filter out None aliases
            filtered_result = []
            for row in result:
                measurement, alias = row
                if alias is not None:
                    filtered_result.append((measurement, alias))

            if filtered_result:
                yield filtered_result
            offset += chunk_size

    def get_measurements_with_coordinates_by_station_chunked(
        self,
        station_id: int,
        chunk_size: int = 1000,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> "typing.Iterator[List[typing.Tuple[datetime, float, float, str, float]]]":
        """Generator that yields measurements with coordinates for a station in chunks.

        Returns tuples of (collection_time, lat, lon, sensor_alias, measurement_value)
        """
        from app.db.models.sensor import Sensor
        from geoalchemy2.functions import ST_X, ST_Y

        offset = 0
        while True:
            stmt = (
                select(
                    Measurement.collectiontime,
                    ST_Y(Measurement.geometry).label("lat"),
                    ST_X(Measurement.geometry).label("lon"),
                    Sensor.alias,
                    Measurement.measurementvalue,
                )
                .join(Sensor, Measurement.sensorid == Sensor.sensorid)
                .filter(Sensor.stationid == station_id)
                .filter(Sensor.alias.is_not(None))
                .order_by(Measurement.collectiontime, Measurement.measurementid)
                .offset(offset)
                .limit(chunk_size)
            )

            if start_date:
                stmt = stmt.filter(Measurement.collectiontime >= start_date)
            if end_date:
                stmt = stmt.filter(Measurement.collectiontime <= end_date)

            result = list(self.db.execute(stmt).all())
            if not result:
                break

            # Convert to tuples for easy processing
            measurements = []
            for row in result:
                collection_time, lat, lon, alias, value = row
                measurements.append((collection_time, lat, lon, alias, value))

            if measurements:
                yield measurements
            offset += chunk_size

    def get_measurements_pivot_by_station_chunked(
        self,
        station_id: int,
        chunk_size: int = 1000,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> "typing.Iterator[List[typing.Dict[str, typing.Any]]]":
        """Generator that yields pre-grouped measurements for a station in chunks.

        Returns dicts with keys: collection_time, lat, lon, sensor_values
        """
        from app.db.models.sensor import Sensor
        from geoalchemy2.functions import ST_X, ST_Y
        from collections import defaultdict

        # Get sensor aliases for this station
        sensor_aliases = self.get_unique_sensor_aliases_for_station(station_id)

        # Use a simpler approach that generates one row per (time, lat, lon) combination
        # First, get all unique (time, lat, lon) combinations
        base_stmt = (
            select(
                Measurement.collectiontime,
                ST_Y(Measurement.geometry).label("lat"),
                ST_X(Measurement.geometry).label("lon"),
            )
            .join(Sensor, Measurement.sensorid == Sensor.sensorid)
            .filter(Sensor.stationid == station_id)
            .filter(Sensor.alias.is_not(None))
            .distinct()
            .order_by(
                Measurement.collectiontime,
                ST_Y(Measurement.geometry),
                ST_X(Measurement.geometry),
            )
        )

        if start_date:
            base_stmt = base_stmt.filter(Measurement.collectiontime >= start_date)
        if end_date:
            base_stmt = base_stmt.filter(Measurement.collectiontime <= end_date)

        offset = 0
        while True:
            # Get a chunk of unique time/location combinations
            unique_combinations = list(
                self.db.execute(base_stmt.offset(offset).limit(chunk_size)).all()
            )

            if not unique_combinations:
                break

            grouped_measurements = []

            for collection_time, lat, lon in unique_combinations:
                # For each unique combination, get all sensor values
                sensor_values = {alias: None for alias in sensor_aliases}

                # Query to get all measurements for this specific time/location
                measurements_stmt = (
                    select(Sensor.alias, Measurement.measurementvalue)
                    .join(Sensor, Measurement.sensorid == Sensor.sensorid)
                    .filter(Sensor.stationid == station_id)
                    .filter(Sensor.alias.is_not(None))
                    .filter(Measurement.collectiontime == collection_time)
                    .filter(ST_Y(Measurement.geometry) == lat)
                    .filter(ST_X(Measurement.geometry) == lon)
                )

                measurements_result = list(self.db.execute(measurements_stmt).all())

                # Populate sensor values
                for alias, value in measurements_result:
                    sensor_values[alias] = value

                grouped_measurements.append(
                    {
                        "collection_time": collection_time,
                        "lat": lat,
                        "lon": lon,
                        "sensor_values": sensor_values,
                        "sensor_aliases": sensor_aliases,
                    }
                )

            if grouped_measurements:
                yield grouped_measurements

            offset += chunk_size
