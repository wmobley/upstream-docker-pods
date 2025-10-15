from datetime import datetime
from typing import Optional, List, Tuple
import logging

from app.api.v1.schemas.sensor import (
    SensorCreateResponse,
    SensorIn,
    GetSensorResponse,
    SensorStatistics,
    SensorItem,
    SensorUpdate,
    ForceUpdateSensorStatisticsResponse,
    UpdateSensorStatisticsResponse
)
from app.db.repositories.sensor_repository import SensorRepository, SortField
from app.db.repositories.measurement_repository import MeasurementRepository
from app.api.v1.schemas.measurement import MeasurementIn


class SensorService:
    def __init__(self, sensor_repository: SensorRepository, measurement_repository: MeasurementRepository):
        self.sensor_repository = sensor_repository
        self.measurement_repository = measurement_repository

    def create_sensor(self, sensor: SensorIn, station_id: int) -> GetSensorResponse:
        response = self.sensor_repository.create_sensor(sensor, station_id)
        return GetSensorResponse(
            id=response.sensorid,
            alias=response.alias,
            description=response.description,
            postprocess=response.postprocess,
            postprocessscript=response.postprocessscript,
            units=response.units,
            variablename=response.variablename,
            statistics=None
        )
    def update_sensor(self, sensor_id: int, sensor: SensorUpdate) -> SensorCreateResponse | None:
        response = self.sensor_repository.update_sensor(sensor_id, sensor)
        if not response:
            return None
        return SensorCreateResponse(
            id=response.sensorid,
        )
    def partial_update_sensor(self, sensor_id: int, sensor: SensorUpdate) -> SensorCreateResponse | None:
        response = self.sensor_repository.update_sensor(sensor_id, sensor, partial=True)
        if not response:
            return None
        return SensorCreateResponse(
            id=response.sensorid,
        )
    def get_sensor(self, sensor_id: int) -> GetSensorResponse | None:
        return self.sensor_repository.get_sensor(sensor_id)

    def get_sensors(
        self,
        station_id: Optional[int] = None,
        variable_name: Optional[str] = None,
        postprocess: Optional[bool] = None,
        page: int = 1,
        limit: int = 20,
        sort_by: Optional[SortField] = None,
        sort_order: str = "asc"
    ) -> Tuple[List[SensorItem], int]:
        rows, total_count = self.sensor_repository.get_sensors(
            station_id=station_id,
            variable_name=variable_name,
            postprocess=postprocess,
            page=page,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order
        )

        items: List[SensorItem] = []
        for row in rows:
            sensor, statistics = row
            item = SensorItem(
                id=sensor.sensorid,
                alias=sensor.alias,
                description=sensor.description,
                postprocess=sensor.postprocess,
                postprocessscript=sensor.postprocessscript,
                units=sensor.units,
                variablename=sensor.variablename,
                statistics=SensorStatistics(
                    max_value=statistics.max_value if statistics else None,
                    min_value=statistics.min_value if statistics else None,
                    avg_value=statistics.avg_value if statistics else None,
                    stddev_value=statistics.stddev_value if statistics else None,
                    percentile_90=statistics.percentile_90 if statistics else None,
                    percentile_95=statistics.percentile_95 if statistics else None,
                    percentile_99=statistics.percentile_99 if statistics else None,
                    count=statistics.count if statistics else None,
                    first_measurement_value=statistics.first_measurement_value if statistics else None,
                    first_measurement_collectiontime=statistics.first_measurement_collectiontime if statistics else None,
                    last_measurement_time=statistics.last_measurement_collectiontime if statistics else None,
                    last_measurement_value=statistics.last_measurement_value if statistics else None,
                    stats_last_updated=statistics.stats_last_updated if statistics else None
                ) if statistics else None
            )
            items.append(item)
        return items, total_count

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
        sort_order: str = "asc"
    ) -> Tuple[List[SensorItem], int]:
        rows, total_count = self.sensor_repository.get_sensors_by_station_id(
            station_id=station_id,
            page=page,
            limit=limit,
            variable_name=variable_name,
            units=units,
            alias=alias,
            description_contains=description_contains,
            postprocess=postprocess,
            sort_by=sort_by,
            sort_order=sort_order
        )

        items: List[SensorItem] = []
        for row in rows:
            sensor, statistics = row
            item = SensorItem(
                id=sensor.sensorid,
                alias=sensor.alias,
                description=sensor.description,
                postprocess=sensor.postprocess,
                postprocessscript=sensor.postprocessscript,
                units=sensor.units,
                variablename=sensor.variablename,
                statistics=SensorStatistics(
                    max_value=statistics.max_value if statistics else None,
                    min_value=statistics.min_value if statistics else None,
                    avg_value=statistics.avg_value if statistics else None,
                    stddev_value=statistics.stddev_value if statistics else None,
                    percentile_90=statistics.percentile_90 if statistics else None,
                    percentile_95=statistics.percentile_95 if statistics else None,
                    percentile_99=statistics.percentile_99 if statistics else None,
                    count=statistics.count if statistics else None,
                    first_measurement_value=statistics.first_measurement_value if statistics else None,
                    first_measurement_collectiontime=statistics.first_measurement_collectiontime if statistics else None,
                    last_measurement_time=statistics.last_measurement_collectiontime if statistics else None,
                    last_measurement_value=statistics.last_measurement_value if statistics else None,
                    stats_last_updated=statistics.stats_last_updated if statistics else None
                ) if statistics else None
            )
            items.append(item)
        return items, total_count

    def delete_sensor(self, sensor_id: int) -> bool:
        return self.sensor_repository.delete_sensor(sensor_id)

    def refresh_sensor_statistics(self, sensor_id: int) -> bool:
        return self.sensor_repository.refresh_sensor_statistics(sensor_id)

    def delete_sensor_measurements(self, sensor_id: int) -> None:
        self.sensor_repository.delete_sensor_statistics(sensor_id)
        self.sensor_repository.delete_sensor_measurements(sensor_id)

    def create_measurement(self, measurement: MeasurementIn, sensor_id: int) -> bool:
        self.measurement_repository.create_measurement(measurement, sensor_id)
        return True

    def bulk_create_measurements(self, measurements: List[MeasurementIn], sensor_id: int) -> bool:
        self.measurement_repository.bulk_create_measurements(measurements, sensor_id)
        return True

    def get_latest_measurement(self, sensor_id: int) -> Optional[datetime]:
        measurement = self.measurement_repository.get_latest_measurement_by_sensor_id(sensor_id)
        return measurement.collectiontime if measurement else None

    def force_update_station_sensor_statistics(self, station_id: int) -> ForceUpdateSensorStatisticsResponse:
        """Force update statistics for all sensors in a station."""
        from app.db.models.sensor import Sensor
        
        # Get all sensors for the station
        sensors = self.sensor_repository.db.query(Sensor).filter(Sensor.stationid == station_id).all()
        sensor_ids = [sensor.sensorid for sensor in sensors]
        updated_sensor_ids = []

        for sensor_id in sensor_ids:
            try:
                self.sensor_repository.delete_sensor_statistics(sensor_id)
                self.sensor_repository.refresh_sensor_statistics(sensor_id)
                updated_sensor_ids.append(sensor_id)
            except Exception:
                # Continue with other sensors if one fails
                logging.warning("Failed to update statistics for sensor ID %s", sensor_id)
                continue

        return ForceUpdateSensorStatisticsResponse(
            updated_sensor_ids=updated_sensor_ids,
            total_updated=len(updated_sensor_ids)
        )

    def force_update_single_sensor_statistics(self, sensor_id: int) -> UpdateSensorStatisticsResponse:
        """Force update statistics for a single sensor."""
        try:
            self.sensor_repository.delete_sensor_statistics(sensor_id)
            self.sensor_repository.refresh_sensor_statistics(sensor_id)
            return UpdateSensorStatisticsResponse(sensor_id=sensor_id, updated=True)
        except Exception as e:
            logging.warning("Failed to update statistics for sensor ID %s: %s", sensor_id, str(e))
            return UpdateSensorStatisticsResponse(sensor_id=sensor_id, updated=False)