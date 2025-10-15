from typing import Optional, List, Tuple, Any
import typing
from sqlalchemy.orm import Session
from sqlalchemy import Row, select, func, Column
from sqlalchemy.sql import text
from enum import Enum

from app.api.v1.schemas.sensor import (
    SensorIn,
    GetSensorResponse,
    SensorStatistics as SensorStatisticsSchema,
    SensorUpdate,
)
from app.db.models.sensor import Sensor
from app.db.models.measurement import Measurement
from app.db.models.sensor_statistics import SensorStatistics


class SortField(str, Enum):
    # Sensor fields
    ALIAS = "alias"
    DESCRIPTION = "description"
    POSTPROCESS = "postprocess"
    POSTPROCESSSCRIPT = "postprocessscript"
    UNITS = "units"
    VARIABLENAME = "variablename"

    # SensorStatistics fields
    MAX_VALUE = "max_value"
    MIN_VALUE = "min_value"
    AVG_VALUE = "avg_value"
    STDDEV_VALUE = "stddev_value"
    PERCENTILE_90 = "percentile_90"
    PERCENTILE_95 = "percentile_95"
    PERCENTILE_99 = "percentile_99"
    COUNT = "count"
    FIRST_MEASUREMENT_VALUE = "first_measurement_value"
    FIRST_MEASUREMENT_COLLECTIONTIME = "first_measurement_collectiontime"
    LAST_MEASUREMENT_VALUE = "last_measurement_value"
    LAST_MEASUREMENT_COLLECTIONTIME = "last_measurement_collectiontime"


class SensorRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_sensor(self, request: SensorIn, station_id: int) -> Sensor:
        db_sensor = Sensor(
            stationid=station_id,
            alias=request.alias,
            description=request.description,
            postprocess=request.postprocess,
            postprocessscript=request.postprocessscript,
            units=request.units,
            variablename=request.variablename,
        )
        self.db.add(db_sensor)
        self.db.commit()
        self.db.refresh(db_sensor)
        return db_sensor

    def create_sensors(self, sensors: list[Sensor]) -> list[Sensor]:
        self.db.add_all(sensors)
        self.db.commit()
        return sensors

    def get_sensor(self, sensor_id: int) -> GetSensorResponse | None:
        stmt = (
            select(Sensor, SensorStatistics)
            .outerjoin(SensorStatistics, Sensor.sensorid == SensorStatistics.sensorid)
            .where(Sensor.sensorid == sensor_id)
        )

        result = self.db.execute(stmt).first()

        if result is None:
            return None

        sensor, statistics = result

        return GetSensorResponse(
            id=sensor.sensorid,
            alias=sensor.alias,
            variablename=sensor.variablename,
            description=sensor.description,
            postprocess=sensor.postprocess,
            postprocessscript=sensor.postprocessscript,
            units=sensor.units,
            statistics=SensorStatisticsSchema(
                max_value=statistics.max_value if statistics else None,
                min_value=statistics.min_value if statistics else None,
                avg_value=statistics.avg_value if statistics else None,
                stddev_value=statistics.stddev_value if statistics else None,
                percentile_90=statistics.percentile_90 if statistics else None,
                percentile_95=statistics.percentile_95 if statistics else None,
                percentile_99=statistics.percentile_99 if statistics else None,
                count=statistics.count if statistics else None,
                first_measurement_value=(
                    statistics.first_measurement_value if statistics else None
                ),
                first_measurement_collectiontime=(
                    statistics.first_measurement_collectiontime if statistics else None
                ),
                last_measurement_time=(
                    statistics.last_measurement_collectiontime if statistics else None
                ),
                last_measurement_value=(
                    statistics.last_measurement_value if statistics else None
                ),
                stats_last_updated=(
                    statistics.stats_last_updated if statistics else None
                ),
            ),
        )

    def delete_sensor_statistics(self, sensor_id: int) -> bool:
        self.db.query(SensorStatistics).filter(
            SensorStatistics.sensorid == sensor_id
        ).delete()
        self.db.commit()
        return True

    def refresh_sensor_statistics(self, sensor_id: int) -> bool:
        self.db.execute(
            text("SELECT refresh_outdated_sensor_statistics(:sensor_id);"),
            {"sensor_id": sensor_id},
        )
        self.db.commit()
        return True

    def delete_sensor_measurements(self, sensor_id: int) -> None:
        self.db.query(Measurement).filter(Measurement.sensorid == sensor_id).delete()
        self.db.commit()

    def get_sort_column(self, sort_by: SortField) -> Column[Any] | None:
        if sort_by.value in [
            SortField.ALIAS.value,
            SortField.DESCRIPTION.value,
            SortField.POSTPROCESS.value,
            SortField.POSTPROCESSSCRIPT.value,
            SortField.UNITS.value,
            SortField.VARIABLENAME.value,
        ]:
            return getattr(Sensor, sort_by.value)  # type: ignore
        elif sort_by.value in [
            SortField.MAX_VALUE.value,
            SortField.MIN_VALUE.value,
            SortField.AVG_VALUE.value,
            SortField.STDDEV_VALUE.value,
            SortField.PERCENTILE_90.value,
            SortField.PERCENTILE_95.value,
            SortField.PERCENTILE_99.value,
            SortField.COUNT.value,
            SortField.FIRST_MEASUREMENT_VALUE.value,
            SortField.FIRST_MEASUREMENT_COLLECTIONTIME.value,
            SortField.LAST_MEASUREMENT_VALUE.value,
            SortField.LAST_MEASUREMENT_COLLECTIONTIME.value,
        ]:
            return getattr(SensorStatistics, sort_by.value)  # type: ignore
        return None

    def get_sensors_by_station_id(
        self,
        station_id: int,
        page: int = 1,
        limit: int = 20,
        variable_name: str | None = None,
        units: str | None = None,
        alias: str | None = None,
        description_contains: str | None = None,
        postprocess: bool | None = None,
        sort_by: Optional[SortField] = None,
        sort_order: str = "asc",
    ) -> Tuple[list[Row[Tuple[Sensor, SensorStatistics]]], int]:
        count_stmt = (
            select(func.count())
            .select_from(Sensor)
            .where(Sensor.stationid == station_id)
        )
        stmt = select(Sensor, SensorStatistics).outerjoin(
            SensorStatistics, Sensor.sensorid == SensorStatistics.sensorid
        )
        stmt = stmt.where(Sensor.stationid == station_id)

        if variable_name:
            stmt = stmt.where(Sensor.variablename.ilike(f"%{variable_name}%"))
            count_stmt = count_stmt.where(
                Sensor.variablename.ilike(f"%{variable_name}%")
            )
        if units:
            stmt = stmt.where(Sensor.units == units)
            count_stmt = count_stmt.where(Sensor.units == units)
        if alias:
            stmt = stmt.where(Sensor.alias.ilike(f"%{alias}%"))
            count_stmt = count_stmt.where(Sensor.alias.ilike(f"%{alias}%"))
        if description_contains:
            stmt = stmt.where(Sensor.description.ilike(f"%{description_contains}%"))
            count_stmt = count_stmt.where(
                Sensor.description.ilike(f"%{description_contains}%")
            )
        if postprocess is not None:
            stmt = stmt.where(Sensor.postprocess == postprocess)
            count_stmt = count_stmt.where(Sensor.postprocess == postprocess)

        # Handle sorting
        if sort_by:
            sort_column = self.get_sort_column(sort_by)
            if sort_column is not None:
                if sort_order.lower() == "desc":
                    stmt = stmt.order_by(sort_column.desc())
                else:
                    stmt = stmt.order_by(sort_column.asc())

        stmt = stmt.limit(limit).offset((page - 1) * limit)
        result = list(self.db.execute(stmt).all())
        total_count = self.db.execute(count_stmt).scalar_one()
        return result, total_count

    def get_sensors(
        self,
        station_id: Optional[int] = None,
        variable_name: Optional[str] = None,
        postprocess: Optional[bool] = None,
        page: int = 1,
        limit: int = 20,
        sort_by: Optional[SortField] = None,
        sort_order: str = "asc",
    ) -> tuple[list[Row[Tuple[Sensor, SensorStatistics]]], int]:
        stmt = select(Sensor, SensorStatistics).outerjoin(
            SensorStatistics, Sensor.sensorid == SensorStatistics.sensorid
        )
        count_stmt = select(func.count()).select_from(Sensor)

        if station_id:
            stmt = stmt.where(Sensor.stationid == station_id)
            count_stmt = count_stmt.where(Sensor.stationid == station_id)
        if variable_name:
            stmt = stmt.where(Sensor.variablename == variable_name)
            count_stmt = count_stmt.where(Sensor.variablename == variable_name)
        if postprocess is not None:
            stmt = stmt.where(Sensor.postprocess == postprocess)
            count_stmt = count_stmt.where(Sensor.postprocess == postprocess)

        # Handle sorting
        if sort_by:
            sort_column = self.get_sort_column(sort_by)
            if sort_column is not None:
                if sort_order.lower() == "desc":
                    stmt = stmt.order_by(sort_column.desc())
                else:
                    stmt = stmt.order_by(sort_column.asc())

        total_count = self.db.execute(count_stmt).scalar_one()
        result = list(
            self.db.execute(stmt.offset((page - 1) * limit).limit(limit)).all()
        )
        return result, total_count

    def delete_sensor(self, sensor_id: int) -> bool:
        db_sensor = self.db.query(Sensor).filter(Sensor.sensorid == sensor_id).first()
        if db_sensor:
            # Database CASCADE will automatically delete measurements and statistics
            self.db.delete(db_sensor)
            self.db.commit()
            return True
        return False

    def list_sensor_variables(self) -> list[str]:
        return [row[0] for row in self.db.query(Sensor.variablename).distinct().all()]

    def get_sensor_by_alias_and_station_id(
        self, alias: str, station_id: int
    ) -> Sensor | None:
        return (
            self.db.query(Sensor)
            .filter(Sensor.alias == alias, Sensor.stationid == station_id)
            .first()
        )

    def update_sensor(
        self, sensor_id: int, request: SensorUpdate, partial: bool = False
    ) -> Sensor | None:

        db_station = self.db.query(Sensor).filter(Sensor.sensorid == sensor_id).first()

        if not db_station:
            return None

        if partial:
            # Get only the fields that were explicitly set in the request
            update_data = request.model_dump(exclude_unset=True)
            field_mapping = {
                "alias": "alias",
                "description": "description",
                "postprocess": "postprocess",
                "postprocessscript": "postprocessscript",
                "units": "units",
                "variablename": "variablename",
            }
            for field, value in update_data.items():
                db_field = field_mapping.get(field, field)
                setattr(db_station, db_field, value)
        else:
            # Full update (existing logic)
            # Ensure all fields for a full update are provided and not None
            alias = request.alias
            description = request.description
            postprocess = request.postprocess
            postprocessscript = request.postprocessscript
            units = request.units
            variablename = request.variablename

            if alias is None:
                raise ValueError("Sensor alias must be provided for a full update")
            if description is None:
                raise ValueError(
                    "Sensor description must be provided for a full update"
                )
            if postprocess is None:
                raise ValueError("postprocess must be provided for a full update")
            if postprocessscript is None:
                raise ValueError("postprocessscript must be provided for a full update")
            if units is None:
                raise ValueError("units must be provided for a full update")
            if variablename is None:
                raise ValueError("variablename must be provided for a full update")

            db_station.alias = alias
            db_station.description = description
            db_station.postprocess = postprocess
            db_station.postprocessscript = postprocessscript
            db_station.units = units
            db_station.variablename = variablename

        self.db.commit()
        self.db.refresh(db_station)
        return db_station

    def get_sensors_by_campaign_chunked(
        self, campaign_id: int, chunk_size: int = 1000
    ) -> "typing.Iterator[List[Sensor]]":
        """Generator that yields sensors for a campaign in chunks."""
        from app.db.models.station import Station

        offset = 0
        while True:
            stmt = (
                select(Sensor)
                .join(Station, Sensor.stationid == Station.stationid)
                .filter(Station.campaignid == campaign_id)
                .order_by(Sensor.sensorid)
                .offset(offset)
                .limit(chunk_size)
            )

            result = list(self.db.execute(stmt).scalars().all())
            if not result:
                break

            yield result
            offset += chunk_size

    def get_sensors_by_station_chunked(
        self, station_id: int, chunk_size: int = 1000
    ) -> "typing.Iterator[List[Sensor]]":
        """Generator that yields sensors for a station in chunks."""
        offset = 0
        while True:
            stmt = (
                select(Sensor)
                .filter(Sensor.stationid == station_id)
                .order_by(Sensor.sensorid)
                .offset(offset)
                .limit(chunk_size)
            )

            result = list(self.db.execute(stmt).scalars().all())
            if not result:
                break

            yield result
            offset += chunk_size
