import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple
from unittest.mock import ANY
import jwt

from app.main import app
from app.db.models.measurement import Measurement as MeasurementModel
from app.api.v1.schemas.measurement import MeasurementItem, AggregatedMeasurement, MeasurementCreateResponse # Assuming MeasurementCreateResponse exists
from app.db.repositories.measurement_repository import MeasurementRepository
from app.db.repositories.sensor_repository import SensorRepository # For delete operation

# Test JWT secret (same as in test_campaign_station_sensors.py)
TEST_JWT_SECRET = "test_secret"
TEST_JWT_ALGORITHM = "HS256"

@pytest.fixture
def client() -> TestClient:
    return TestClient(app)

@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Create authentication headers with a JWT token"""
    payload = {
        "sub": "test_user",
        "exp": datetime.utcnow() + timedelta(minutes=30),
        "iat": datetime.utcnow(),
    }
    token = jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def sample_measurement_model_data() -> List[Tuple[MeasurementModel, str]]:
    # Helper to create MeasurementModel instances for repository mock
    # The actual MeasurementModel would have more fields if fully fleshed out
    m1 = MeasurementModel(
        measurementid=1, sensorid=1, variablename="temp", collectiontime=datetime.utcnow() - timedelta(hours=1),
        measurementvalue=25.5, variabletype="float", description="temp reading 1"
    )
    m1_geojson = '{"type": "Point", "coordinates": [10.0, 20.0]}'
    m2 = MeasurementModel(
        measurementid=2, sensorid=1, variablename="temp", collectiontime=datetime.utcnow(),
        measurementvalue=26.0, variabletype="float", description="temp reading 2"
    )
    m2_geojson = '{"type": "Point", "coordinates": [10.1, 20.1]}'
    return [(m1, m1_geojson), (m2, m2_geojson)]

@pytest.fixture
def sample_aggregated_measurements_data() -> List[AggregatedMeasurement]:
    return [
        # Adjusted to match the AggregatedMeasurement schema
        AggregatedMeasurement(
            measurement_time=datetime.utcnow().replace(minute=0, second=0, microsecond=0),
            value=25.0, # formerly avg_value
            median_value=24.5, # Added
            min_value=20.0,
            max_value=30.0,
            point_count=10, # formerly count
            std_dev=2.5, # formerly stddev_value
            lower_bound=22.5, # formerly lower_confidence_interval
            upper_bound=27.5, # formerly upper_confidence_interval
            parametric_lower_bound=22.0, # Added
            parametric_upper_bound=28.0, # Added
            percentile_25=23.0, # Added
            percentile_75=27.0, # Added
            ci_method="percentile", # Added
            confidence_level=0.95) # Added
    ]

@pytest.fixture
def mock_measurement_repo(
    sample_measurement_model_data: List[Tuple[MeasurementModel, str]],
    sample_aggregated_measurements_data: List[AggregatedMeasurement]
) -> MagicMock:
    repository = MagicMock(spec=MeasurementRepository)

    def list_measurements_mock(
        sensor_id: int, page: int, limit: int, start_date: Any, end_date: Any,
        min_value: Any, max_value: Any, # variable_name is not a param in route
        # downsample_threshold is handled by service, repo just returns data
    ) -> Tuple[List[Tuple[MeasurementModel, str]], int, float | None, float | None, float | None]:
        # Simulate filtering and pagination based on inputs if needed for more complex tests
        # For now, return sample data
        paginated_data = sample_measurement_model_data[(page-1)*limit : page*limit]
        return paginated_data, len(sample_measurement_model_data), 25.0, 26.0, 25.75

    repository.list_measurements.side_effect = list_measurements_mock
    repository.get_measurements_with_confidence_intervals.return_value = sample_aggregated_measurements_data

    # For PUT/PATCH
    def update_measurement_mock(measurement_id: int, request: Any, partial: bool = False) -> MeasurementModel | None:
        if measurement_id == 1: # Assume measurement 1 exists
            updated_model = MeasurementModel(
                measurementid=measurement_id,
                sensorid=request.sensorid if request.sensorid is not None else 1, # Example default
                collectiontime=request.collectiontime if request.collectiontime else datetime.utcnow(),
                measurementvalue=request.measurementvalue if request.measurementvalue is not None else 30.0,
                variabletype=request.variabletype if request.variabletype else "float",
                description=request.description if request.description else "Updated measurement"
                # geometry would also be handled here
            )
            return updated_model
        return None
    repository.update_measurement.side_effect = update_measurement_mock
    return repository

@pytest.fixture
def mock_sensor_repo_for_delete() -> MagicMock:
    repository = MagicMock(spec=SensorRepository)
    repository.delete_sensor_measurements.return_value = None # Method is void
    # SensorService.delete_sensor_measurements also calls delete_sensor_statistics
    repository.delete_sensor_statistics.return_value = True # Assuming it returns bool or is void
    return repository

# Common path parameters
CAMPAIGN_ID = 1
STATION_ID = 1
SENSOR_ID = 1
MEASUREMENT_ID = 1

# --- Test GET /measurements ---
@patch('app.api.v1.routes.campaigns.campaign_station_sensor_measurements.MeasurementRepository')
@patch('app.core.config.get_settings')
@patch('app.api.v1.routes.campaigns.campaign_station_sensor_measurements.check_allocation_permission', return_value=True)
def test_get_sensor_measurements_success(
    mock_check_alloc: MagicMock,
    mock_get_settings: MagicMock,
    mock_repo_class: MagicMock,
    client: TestClient,
    auth_headers: Dict[str, str],
    mock_measurement_repo: MagicMock,
    sample_measurement_model_data: List[Tuple[MeasurementModel, str]]
):
    mock_repo_class.return_value = mock_measurement_repo
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    response = client.get(
        f"/api/v1/campaigns/{CAMPAIGN_ID}/stations/{STATION_ID}/sensors/{SENSOR_ID}/measurements?page=1&limit=10",
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == len(sample_measurement_model_data)
    assert len(data["items"]) == len(sample_measurement_model_data) # Assuming limit > total
    assert data["items"][0]["id"] == sample_measurement_model_data[0][0].measurementid
    assert data["items"][0]["value"] == sample_measurement_model_data[0][0].measurementvalue
    # A more robust way to check mock_check_alloc would be to inspect its call_args if current_user was mocked
    # For now, this is a placeholder for the call check
    mock_check_alloc.assert_called_once() # Simplified check
    mock_measurement_repo.list_measurements.assert_called_once()

@patch('app.core.config.get_settings')
@patch('app.api.v1.routes.campaigns.campaign_station_sensor_measurements.check_allocation_permission', return_value=False)
def test_get_sensor_measurements_allocation_denied(
    mock_check_alloc: MagicMock,
    mock_get_settings: MagicMock,
    client: TestClient,
    auth_headers: Dict[str, str]
):
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    response = client.get(
        f"/api/v1/campaigns/{CAMPAIGN_ID}/stations/{STATION_ID}/sensors/{SENSOR_ID}/measurements",
        headers=auth_headers
    )
    assert response.status_code == 404 # As per route's HTTPException
    assert response.json()["detail"] == "Allocation is incorrect"

@patch('app.core.config.get_settings')
def test_get_sensor_measurements_unauthorized(
    mock_get_settings: MagicMock,
    client: TestClient
):
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET # Need this for the app to load the auth backend
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings
    response = client.get(
        f"/api/v1/campaigns/{CAMPAIGN_ID}/stations/{STATION_ID}/sensors/{SENSOR_ID}/measurements"
    )
    assert response.status_code == 401


# --- Test GET /measurements/confidence-intervals ---
@patch('app.api.v1.routes.campaigns.campaign_station_sensor_measurements.MeasurementRepository')
@patch('app.core.config.get_settings')
# Note: The route being tested below currently lacks authentication and authorization checks (`get_current_user`, `check_allocation_permission`).
# This might be a potential security oversight in the application code.
def test_get_measurements_confidence_intervals_success(
    mock_get_settings: MagicMock, # Still need for app load if auth is generally configured
    mock_repo_class: MagicMock,
    client: TestClient,
    mock_measurement_repo: MagicMock,
    sample_aggregated_measurements_data: List[AggregatedMeasurement]
):
    mock_repo_class.return_value = mock_measurement_repo
    mock_settings = MagicMock(); mock_settings.JWT_SECRET = TEST_JWT_SECRET; mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    response = client.get(
        f"/api/v1/campaigns/{CAMPAIGN_ID}/stations/{STATION_ID}/sensors/{SENSOR_ID}/measurements/confidence-intervals"
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == len(sample_aggregated_measurements_data)
    assert data[0]["value"] == sample_aggregated_measurements_data[0].value # Changed from avg_value to value
    mock_measurement_repo.get_measurements_with_confidence_intervals.assert_called_once()

# --- Test PUT /measurements/{measurement_id} ---
MOCK_MEASUREMENT_UPDATE_PAYLOAD = {
    "measurementvalue": 30.5,
    "description": "Updated via PUT"
}

# A full payload is required for PUT, as the repository enforces this for non-partial updates.
MOCK_FULL_MEASUREMENT_UPDATE_PAYLOAD = {
    "sensorid": SENSOR_ID,
    "collectiontime": datetime.utcnow().isoformat(),
    "geometry": "POINT(10.0 20.0)",
    "measurementvalue": 30.5,
    "variablename": "temp",
    "variabletype": "float",
    "description": "Updated via PUT"
}

@patch('app.api.v1.routes.campaigns.campaign_station_sensor_measurements.MeasurementRepository')
@patch('app.core.config.get_settings')
@patch('app.api.v1.routes.campaigns.campaign_station_sensor_measurements.check_allocation_permission', return_value=True)
def test_update_measurement_success( 
    mock_check_alloc: MagicMock,
    mock_get_settings: MagicMock,
    mock_repo_class: MagicMock,
    client: TestClient,
    auth_headers: Dict[str, str],
    mock_measurement_repo: MagicMock
):
    mock_repo_class.return_value = mock_measurement_repo
    mock_settings = MagicMock(); mock_settings.JWT_SECRET = TEST_JWT_SECRET; mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    response = client.put(
        f"/api/v1/campaigns/{CAMPAIGN_ID}/stations/{STATION_ID}/sensors/{SENSOR_ID}/measurements/{MEASUREMENT_ID}",
        json=MOCK_FULL_MEASUREMENT_UPDATE_PAYLOAD,
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    # The service returns a MeasurementCreateResponse with the sensorid, not the measurementid.
    # Our mock ensures the sensorid from the request is used.
    assert data["id"] == SENSOR_ID
    
    # Verify the repository was called correctly for a full update (partial=False)
    mock_measurement_repo.update_measurement.assert_called_once_with(MEASUREMENT_ID, ANY)



@patch('app.api.v1.routes.campaigns.campaign_station_sensor_measurements.MeasurementRepository')
@patch('app.core.config.get_settings')
@patch('app.api.v1.routes.campaigns.campaign_station_sensor_measurements.check_allocation_permission', return_value=True)
def test_update_measurement_not_found(
    mock_check_alloc: MagicMock,
    mock_get_settings: MagicMock,
    mock_repo_class: MagicMock,
    client: TestClient,
    auth_headers: Dict[str, str],
    mock_measurement_repo: MagicMock
):
    mock_repo_class.return_value = mock_measurement_repo
    mock_measurement_repo.update_measurement.return_value = None 
    mock_settings = MagicMock(); mock_settings.JWT_SECRET = TEST_JWT_SECRET; mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    non_existent_measurement_id = 999
    response = client.put(
        f"/api/v1/campaigns/{CAMPAIGN_ID}/stations/{STATION_ID}/sensors/{SENSOR_ID}/measurements/{non_existent_measurement_id}",
        json=MOCK_FULL_MEASUREMENT_UPDATE_PAYLOAD,
        headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Measurement not found"


# --- Test PATCH /measurements/{measurement_id} ---
MOCK_MEASUREMENT_PARTIAL_UPDATE_PAYLOAD = {
    "description": "Updated via PATCH"
}

@patch('app.api.v1.routes.campaigns.campaign_station_sensor_measurements.MeasurementRepository')
@patch('app.core.config.get_settings')
@patch('app.api.v1.routes.campaigns.campaign_station_sensor_measurements.check_allocation_permission', return_value=True)
def test_partial_update_measurement_success( 
    mock_check_alloc: MagicMock,
    mock_get_settings: MagicMock,
    mock_repo_class: MagicMock,
    client: TestClient,
    auth_headers: Dict[str, str],
    mock_measurement_repo: MagicMock
):
    mock_repo_class.return_value = mock_measurement_repo
    mock_settings = MagicMock(); mock_settings.JWT_SECRET = TEST_JWT_SECRET; mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    response = client.patch(
        f"/api/v1/campaigns/{CAMPAIGN_ID}/stations/{STATION_ID}/sensors/{SENSOR_ID}/measurements/{MEASUREMENT_ID}",
        json=MOCK_MEASUREMENT_PARTIAL_UPDATE_PAYLOAD,
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    # The service returns a MeasurementCreateResponse with the sensorid.
    # The mock defaults to sensorid=1, which matches SENSOR_ID.
    assert data["id"] == SENSOR_ID

    # Verify the repository was called correctly for a partial update (partial=True)
    mock_measurement_repo.update_measurement.assert_called_once_with(MEASUREMENT_ID, ANY, partial=True)