from datetime import datetime
from typing import List, Optional, Union

from pydantic import BaseModel

from app.api.v1.schemas.measurement import MeasurementIn


# Pydantic model for incoming sensor data
class SensorIn(BaseModel):
    alias: Union[str, float]
    description: Optional[str] = None
    postprocess: Optional[bool] = True
    postprocessscript: Optional[str] = None
    units: Optional[str] = None
    variablename: Optional[str] = None

class SensorCreateResponse(BaseModel):
    id: int

class SensorStatistics(BaseModel):
    max_value: Optional[float] = None
    min_value: Optional[float] = None
    avg_value: Optional[float] = None
    stddev_value: Optional[float] = None
    percentile_90: Optional[float] = None
    percentile_95: Optional[float] = None
    percentile_99: Optional[float] = None
    count: Optional[int] = None
    first_measurement_value: Optional[float] = None
    first_measurement_collectiontime: Optional[datetime] = None
    last_measurement_time: Optional[datetime] = None
    last_measurement_value: Optional[float] = None
    stats_last_updated: Optional[datetime] = None


class SensorItem(BaseModel):
    id: int
    alias: Optional[str] = None
    description: Optional[str] = None
    postprocess: Optional[bool] = True
    postprocessscript: Optional[str] = None
    units: Optional[str] = None
    variablename: Optional[str] = None
    statistics: Optional[SensorStatistics] = None

class ListSensorsResponse(SensorItem):
    pass


class GetSensorResponse(SensorItem):
    statistics: Optional[SensorStatistics] = None

# Pydantic model for incoming sensor and measurement data
class SensorAndMeasurementIn(BaseModel):
    sensor: SensorIn
    measurement: List[MeasurementIn]


class ListSensorsResponsePagination(BaseModel):
    items: List[SensorItem]
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
    variablename: Optional[str] = None


class ForceUpdateSensorStatisticsResponse(BaseModel):
    updated_sensor_ids: List[int]
    total_updated: int


class UpdateSensorStatisticsResponse(BaseModel):
    sensor_id: int
    updated: bool
