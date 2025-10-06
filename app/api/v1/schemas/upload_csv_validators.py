# type: ignore
from datetime import datetime
from typing import Optional
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    field_validator,
)
from dateutil.parser import parse


class SensorCSV(BaseModel):

    alias: str
    variablename: str | None = Field(alias='BestGuessFormula', default=None)
    postprocess: bool | None = Field(default=True)
    postprocessscript: str | None = Field(default=None)
    description: str | None = Field(default=None)
    units: str | None = Field(default=None)

    @field_validator('alias', mode="before")
    @classmethod
    def float_to_str(cls, value):
        return str(float(value))


class CollTimeCSV(BaseModel):
    collection_time: datetime

    @field_validator('collection_time', mode="before")
    @classmethod
    def parse_datetime(cls, value):
        if isinstance(value, str):
            try:
                return parse(value)
            except Exception as ex:
                raise ValueError (str(ex))
        return value

class LocationCSV(BaseModel):
    long_deg: float
    lat_deg: float

class MeasurementCSV(BaseModel):
    measurement_value: float