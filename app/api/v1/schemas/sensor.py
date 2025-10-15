from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from app.api.v1.schemas.measurement import MeasurementIn


# Pydantic model for incoming sensor data
class SensorIn(BaseModel):
    alias: str | float
    description: Optional[str] = None
    postprocess: Optional[bool] = True
    postprocessscript: Optional[str] = None
    units: Optional[str] = None
    variablename: str | None = None

class SensorCreateResponse(BaseModel):
    id: int

class SensorStatistics(BaseModel):
    max_value: float | None = None
    min_value: float | None = None
    avg_value: float | None = None
    stddev_value: float | None = None
    percentile_90: float | None = None
    percentile_95: float | None = None
    percentile_99: float | None = None
    count: int | None = None
    first_measurement_value: float | None = None
    first_measurement_collectiontime: datetime | None = None
    last_measurement_time: datetime | None = None
    last_measurement_value: float | None = None
    stats_last_updated: datetime | None = None


class SensorItem(BaseModel):
    id: int
    alias: str | None = None
    description: str | None = None
    postprocess: bool | None = True
    postprocessscript: str | None = None
    units: str | None = None
    variablename: str | None = None
    statistics: SensorStatistics | None = None

class ListSensorsResponse(SensorItem):
    pass


class GetSensorResponse(SensorItem):
    statistics: SensorStatistics | None = None

# Pydantic model for incoming sensor and measurement data
class SensorAndMeasurementIn(BaseModel):
    sensor: SensorIn
    measurement: List[MeasurementIn]


class ListSensorsResponsePagination(BaseModel):
    items: list[SensorItem]
    total: int
    page: int
    size: int
    pages: int


class SensorUpdate(BaseModel):
    alias: Optional[str] = None
    description: Optional[str] = None
    postprocess: Optional[bool] = True
    postprocessscript: Optional[str] = None
    units: Optional[str] = None
    variablename: Optional[str] | None = None


class ForceUpdateSensorStatisticsResponse(BaseModel):
    updated_sensor_ids: List[int]
    total_updated: int


class UpdateSensorStatisticsResponse(BaseModel):
    sensor_id: int
    updated: bool