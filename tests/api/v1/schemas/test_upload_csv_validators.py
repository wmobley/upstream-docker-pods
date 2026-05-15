import pytest
from datetime import datetime
from pydantic import ValidationError
from app.api.v1.schemas.upload_csv_validators import (
    SensorCSV,
    CollTimeCSV,
    LocationCSV,
    MeasurementCSV
)

# SensorCSV Tests
def test_sensor_csv_valid():
    data = {
        "alias": "123.0",
        "BestGuessFormula": "temperature",
        "postprocess": True,
        "postprocessscript": "custom_script",
        "description": "Temperature sensor",
        "units": "celsius"
    }
    sensor = SensorCSV(**data)
    assert sensor.alias == "123.0"
    assert sensor.variablename == "temperature"
    assert sensor.postprocess is True
    assert sensor.postprocessscript == "custom_script"
    assert sensor.description == "Temperature sensor"
    assert sensor.units == "celsius"

def test_sensor_csv_float_to_str():
    data = {"alias": 123.0}
    sensor = SensorCSV(**data)
    assert sensor.alias == "123.0"

def test_sensor_csv_minimal():
    data = {"alias": "123.0"}
    sensor = SensorCSV(**data)
    assert sensor.alias == "123.0"
    assert sensor.variablename is None
    assert sensor.postprocess is True
    assert sensor.postprocessscript is None
    assert sensor.description is None
    assert sensor.units is None

# CollTimeCSV Tests
def test_coll_time_csv_valid_datetime():
    data = {"collection_time": "2024-03-15 14:30:00"}
    coll_time = CollTimeCSV(**data)
    assert isinstance(coll_time.collection_time, datetime)
    assert coll_time.collection_time.year == 2024
    assert coll_time.collection_time.month == 3
    assert coll_time.collection_time.day == 15

def test_coll_time_csv_invalid_datetime():
    with pytest.raises(ValidationError) as exc_info:
        CollTimeCSV(**{"collection_time": "invalid_date"})
    assert "collection_time" in str(exc_info.value)

def test_coll_time_csv_with_datetime_object():
    dt = datetime(2024, 3, 15, 14, 30)
    data = {"collection_time": dt}
    coll_time = CollTimeCSV(**data)
    assert coll_time.collection_time == dt

# LocationCSV Tests
def test_location_csv_valid():
    data = {
        "long_deg": -97.7431,
        "lat_deg": 30.2672
    }
    location = LocationCSV(**data)
    assert location.long_deg == -97.7431
    assert location.lat_deg == 30.2672

def test_location_csv_invalid_types():
    with pytest.raises(ValidationError):
        LocationCSV(**{
            "long_deg": "invalid",
            "lat_deg": "invalid"
        })

# MeasurementCSV Tests
def test_measurement_csv_valid():
    data = {"measurement_value": 23.5}
    measurement = MeasurementCSV(**data)
    assert measurement.measurement_value == 23.5

def test_measurement_csv_invalid_type():
    with pytest.raises(ValidationError):
        MeasurementCSV(**{"measurement_value": "invalid"})
