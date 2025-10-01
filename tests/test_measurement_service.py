from unittest.mock import patch, Mock
from geoalchemy2 import Geometry
import pytest
from datetime import datetime, timedelta
from typing import Optional
from geojson_pydantic import Point
from app.api.v1.schemas.measurement import MeasurementItem, ListMeasurementsResponsePagination
from app.services.measurement_service import MeasurementService
from app.db.repositories.measurement_repository import MeasurementRepository

# Mock data for testing
def create_mock_measurement(id_value: int, measurement_value: float, collection_time: datetime, geometry: Optional[Point] = None) -> MeasurementItem:
    if geometry is None:
        geometry = {"type": "Point", "coordinates": [10.0, 20.0]}

    return MeasurementItem(
        id=id_value,
        value=measurement_value,
        collectiontime=collection_time,
        geometry=geometry,
        sensorid=1,
        variablename="temperature",
        variabletype="float",
        description="Temperature reading"
    )

def create_mock_measurements(count: int = 100) -> list[MeasurementItem]:
    """Create a list of mock measurements for testing"""
    base_time = datetime.now()
    measurements = []

    for i in range(count):
        time = base_time - timedelta(minutes=i)
        value = 20 + (i % 10)  # Create some variation in values
        measurements.append(create_mock_measurement(i+1, value, time))

    return measurements

class MockRow:
    """Mock for database row objects"""
    def __init__(self, id_value: int, value: float, time: datetime):
        self.measurementid = id_value
        self.measurementvalue = value
        self.collectiontime = time
        self.description = "Temperature reading"
        self.variabletype = "float"
        self.variablename = "temperature"
        self.sensorid = 1
        self.geometry = "POINT(10.0 20.0)"

@pytest.fixture
def measurement_service() -> MeasurementService:
    """Create a MeasurementService with a mocked repository"""
    mock_repository = Mock(spec=MeasurementRepository)
    return MeasurementService(mock_repository)

def test_list_measurements_no_downsampling(measurement_service: MeasurementService) -> None:
    """Test list_measurements without downsampling"""
    # Arrange
    mock_measurements = create_mock_measurements(20)
    total_count = len(mock_measurements)

    # Create mock rows that would be returned by repository
    mock_rows = []
    for m in mock_measurements:
        mock_row = MockRow(m.id, m.value, m.collectiontime)
        mock_rows.append((mock_row, '{"type":"Point","coordinates":[10.0,20.0]}'))

    measurement_service.measurement_repository.list_measurements.return_value = (
        mock_rows,
        total_count,
        10.0,  # min value
        30.0,  # max value
        20.0   # avg value
    )

    # Act
    result = measurement_service.list_measurements(
        sensor_id=1,
        start_date=None,
        end_date=None,
        min_value=None,
        max_value=None,
        page=1,
        limit=20,
        downsample_threshold=None  # No downsampling
    )

    # Assert
    assert isinstance(result, ListMeasurementsResponsePagination)
    assert result.total == total_count
    assert result.page == 1
    assert result.size == 20
    assert result.pages == 2  # total_count // limit
    assert result.downsampled is False
    assert result.downsampled_total is None
    assert len(result.items) == 20
    assert result.min_value == 10.0
    assert result.max_value == 30.0
    assert result.average_value == 20.0

def test_list_measurements_with_downsampling(measurement_service: MeasurementService) -> None:
    """Test list_measurements with downsampling enabled"""
    # Arrange
    mock_measurements = create_mock_measurements(100)
    total_count = len(mock_measurements)
    downsample_threshold = 10

    # Create mock rows that would be returned by repository
    mock_rows = []
    for m in mock_measurements:
        mock_row = MockRow(m.id, m.value, m.collectiontime)
        mock_rows.append((mock_row, '{"type":"Point","coordinates":[10.0,20.0]}'))

    measurement_service.measurement_repository.list_measurements.return_value = (
        mock_rows,
        total_count,
        10.0,  # min value
        30.0,  # max value
        20.0   # avg value
    )

    # Act
    with patch('app.services.measurement_service.lttb') as mock_lttb:
        # Mock the downsampling result to return exactly downsample_threshold items
        mock_lttb.return_value = mock_measurements[:downsample_threshold]

        result = measurement_service.list_measurements(
            sensor_id=1,
            start_date=None,
            end_date=None,
            min_value=None,
            max_value=None,
            page=1,
            limit=20,
            downsample_threshold=downsample_threshold
        )

    # Assert
    assert isinstance(result, ListMeasurementsResponsePagination)
    assert result.total == total_count
    assert result.page == 1
    assert result.size == 20
    assert result.pages == 2  # len(downsampled) // downsample_threshold
    assert result.downsampled is True
    assert result.downsampled_total == downsample_threshold  # Equal to the number of items after downsampling
    assert len(result.items) == downsample_threshold
    assert result.min_value == 10.0
    assert result.max_value == 30.0
    assert result.average_value == 20.0

    # Verify that lttb was called with the correct arguments
    with patch('app.services.measurement_service.lttb') as mock_lttb:
        measurement_service.list_measurements(
            sensor_id=1, start_date=None, end_date=None,
            min_value=None, max_value=None, page=1,
            limit=20, downsample_threshold=downsample_threshold
        )
        mock_lttb.assert_called_once()

def test_list_measurements_downsampling_pages_calculation(measurement_service: MeasurementService) -> None:
    """Test pages calculation with downsampling enabled"""
    # Arrange
    mock_measurements = create_mock_measurements(100)
    total_count = len(mock_measurements)
    downsample_threshold = 30
    downsampled_result_count = 40  # Mock result after downsampling

    # Create mock rows that would be returned by repository
    mock_rows = []
    for m in mock_measurements:
        mock_row = MockRow(m.id, m.value, m.collectiontime)
        mock_rows.append((mock_row, '{"type":"Point","coordinates":[10.0,20.0]}'))

    measurement_service.measurement_repository.list_measurements.return_value = (
        mock_rows,
        total_count,
        10.0,  # min value
        30.0,  # max value
        20.0   # avg value
    )

    # Act
    with patch('app.services.measurement_service.lttb') as mock_lttb:
        # Mock downsampling to return a specific number of items
        mock_lttb.return_value = mock_measurements[:downsampled_result_count]

        result = measurement_service.list_measurements(
            sensor_id=1,
            start_date=None,
            end_date=None,
            min_value=None,
            max_value=None,
            page=1,
            limit=20,
            downsample_threshold=downsample_threshold
        )

    # Assert
    assert result.pages == downsampled_result_count // downsample_threshold + 1  # 40 // 30 + 1 = 2
    assert result.downsampled is True
    assert result.downsampled_total == downsampled_result_count