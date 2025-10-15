from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from typing import Tuple, List, Dict, Any, Optional
import pytest
import jwt
from fastapi.testclient import TestClient
from app.main import app
from app.db.models.sensor import Sensor
from app.db.repositories.sensor_repository import SensorRepository, SortField
from app.db.models.sensor_statistics import SensorStatistics

# Test JWT secret
TEST_JWT_SECRET = "test_secret"
TEST_JWT_ALGORITHM = "HS256"

@pytest.fixture
def client() -> TestClient:
    return TestClient(app)

@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Create authentication headers with a JWT token"""
    # Create a test token
    payload = {
        "sub": "test_user",
        "exp": datetime.utcnow() + timedelta(minutes=30),
        "iat": datetime.utcnow(),
    }
    token = jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def sample_sensors() -> list[Sensor]:
    return [
        Sensor(
            sensorid=1,
            stationid=1,
            alias="temp_sensor",
            description="Temperature sensor with post-processing",
            postprocess=True,
            postprocessscript="temp * 1.8 + 32",
            units="°F",
            variablename="temperature"
        ),
        Sensor(
            sensorid=2,
            stationid=1,
            alias="humidity_sensor",
            description="Humidity measurement sensor",
            postprocess=False,
            postprocessscript=None,
            units="%",
            variablename="humidity"
        ),
        Sensor(
            sensorid=3,
            stationid=1,
            alias="pressure_sensor",
            description="Atmospheric pressure sensor",
            postprocess=True,
            postprocessscript="pressure * 0.000145038",
            units="psi",
            variablename="pressure"
        )
    ]

@pytest.fixture
def sample_statistics() -> list[SensorStatistics]:
    return [
        SensorStatistics(
            sensorid=1,
            max_value=10,
            min_value=0,
            avg_value=5,
            stddev_value=2,
            percentile_90=9,
            percentile_95=9.5,
            percentile_99=9.9,
            count=100,
            last_measurement_collectiontime=datetime.now(),
            last_measurement_value=5,
            stats_last_updated=datetime.now()
        ),
        SensorStatistics(
            sensorid=2,
            max_value=10,
            min_value=0,
            avg_value=5,
            stddev_value=2,
            percentile_90=9,
            percentile_95=9.5,
            percentile_99=9.9,
            count=100,
            last_measurement_collectiontime=datetime.now(),
            last_measurement_value=5,
            stats_last_updated=datetime.now()
        ),
        SensorStatistics(
            sensorid=3,
            max_value=10,
            min_value=0,
            avg_value=5,
            stddev_value=2,
            percentile_90=9,
            percentile_95=9.5,
            percentile_99=9.9,
            count=100,
            last_measurement_collectiontime=datetime.now(),
        )
    ]


@pytest.fixture
def mock_sensor_repository(sample_sensors: list[Sensor], sample_statistics: list[SensorStatistics]) -> MagicMock:
    repository = MagicMock(spec=SensorRepository)

    def get_sensors_by_station_id_mock(
        station_id: int,
        page: int = 1,
        limit: int = 20,
        variable_name: str | None = None,
        units: str | None = None,
        alias: str | None = None,
        description_contains: str | None = None,
        postprocess: bool | None = None,
        sort_by: SortField | None = None,
        sort_order: str = "asc"
    ) -> Tuple[List[Tuple[Sensor, SensorStatistics]], int]:
        # Filter sensors based on parameters
        filtered_sensors = sample_sensors.copy()
        filtered_stats = sample_statistics.copy()

        # Apply station_id filter
        filtered_sensors = [s for s in filtered_sensors if s.stationid == station_id]

        # Apply variable_name filter
        if variable_name:
            filtered_sensors = [s for s in filtered_sensors if s.variablename and variable_name.lower() in s.variablename.lower()]

        # Apply units filter
        if units:
            filtered_sensors = [s for s in filtered_sensors if s.units == units]

        # Apply alias filter
        if alias:
            filtered_sensors = [s for s in filtered_sensors if s.alias and alias.lower() in s.alias.lower()]

        # Apply description filter
        if description_contains:
            filtered_sensors = [s for s in filtered_sensors if s.description and description_contains in s.description]

        # Apply postprocess filter
        if postprocess is not None:
            filtered_sensors = [s for s in filtered_sensors if s.postprocess == postprocess]

        # Apply sorting
        if sort_by:
            reverse = sort_order.lower() == "desc"
            if sort_by.value in ["alias", "description", "postprocess", "postprocessscript", "units", "variablename"]:
                filtered_sensors.sort(key=lambda x: getattr(x, sort_by.value) or "", reverse=reverse)
            elif sort_by.value in [
                "max_value", "min_value", "avg_value", "stddev_value",
                "percentile_90", "percentile_95", "percentile_99", "count",
                "first_measurement_value", "first_measurement_collectiontime",
                "last_measurement_value", "last_measurement_collectiontime"
            ]:
                # Sort by statistics
                filtered_sensors_with_stats = list(zip(filtered_sensors, filtered_stats))
                filtered_sensors_with_stats.sort(
                    key=lambda x: getattr(x[1], sort_by.value) if x[1] else 0.0,  # Use 0.0 as default for numeric fields
                    reverse=reverse
                )
                filtered_sensors = [s[0] for s in filtered_sensors_with_stats]
                filtered_stats = [s[1] for s in filtered_sensors_with_stats]

        # Apply pagination
        total_count = len(filtered_sensors)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_sensors = filtered_sensors[start_idx:end_idx]
        paginated_statistics = filtered_stats[start_idx:end_idx]

        # Create a list of tuples with sensor and statistics
        result = [(sensor, stats) for sensor, stats in zip(paginated_sensors, paginated_statistics)]
        return result, total_count

    repository.get_sensors_by_station_id.side_effect = get_sensors_by_station_id_mock
    return repository

@patch('app.api.v1.routes.campaigns.campaign_station_sensors.SensorRepository')
@patch('app.core.config.get_settings')
def test_list_sensors_basic(mock_get_settings: MagicMock, mock_repository_class: MagicMock, client: TestClient, sample_sensors: list[Sensor], mock_sensor_repository: MagicMock, auth_headers: Dict[str, str]) -> None:
    # Setup mocks
    mock_repository_class.return_value = mock_sensor_repository
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    # Make request with auth headers
    response = client.get("/api/v1/campaigns/1/stations/1/sensors", headers=auth_headers)

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 3
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["size"] == 20
    assert data["pages"] == 1
    return None


@patch('app.api.v1.routes.campaigns.campaign_station_sensors.SensorRepository')
@patch('app.core.config.get_settings')
def test_list_sensors_with_variable_name_filter(mock_get_settings: MagicMock, mock_repository_class: MagicMock, client: TestClient, sample_sensors: list[Sensor], mock_sensor_repository: MagicMock, auth_headers: Dict[str, str]) -> None:
    # Setup mocks
    mock_repository_class.return_value = mock_sensor_repository
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    # Make request with auth headers
    response = client.get("/api/v1/campaigns/1/stations/1/sensors?variable_name=temp", headers=auth_headers)

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["variablename"] == "temperature"
    return None

@patch('app.api.v1.routes.campaigns.campaign_station_sensors.SensorRepository')
@patch('app.core.config.get_settings')
def test_list_sensors_with_units_filter(mock_get_settings: MagicMock, mock_repository_class: MagicMock, client: TestClient, sample_sensors: list[Sensor], mock_sensor_repository: MagicMock, auth_headers: Dict[str, str]) -> None:
    # Setup mocks
    mock_repository_class.return_value = mock_sensor_repository
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    # Make request with auth headers
    response = client.get("/api/v1/campaigns/1/stations/1/sensors?units=%", headers=auth_headers)

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["units"] == "%"


@patch('app.api.v1.routes.campaigns.campaign_station_sensors.SensorRepository')
@patch('app.core.config.get_settings')
def test_list_sensors_with_alias_filter(mock_get_settings: MagicMock, mock_repository_class: MagicMock, client: TestClient, sample_sensors: list[Sensor], mock_sensor_repository: MagicMock, auth_headers: Dict[str, str]) -> None:
    # Setup mocks
    mock_repository_class.return_value = mock_sensor_repository
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    # Make request with auth headers
    response = client.get("/api/v1/campaigns/1/stations/1/sensors?alias=temp", headers=auth_headers)

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["alias"] == "temp_sensor"
    return None

@patch('app.api.v1.routes.campaigns.campaign_station_sensors.SensorRepository')
@patch('app.core.config.get_settings')
def test_list_sensors_with_description_filter(mock_get_settings: MagicMock, mock_repository_class: MagicMock, client: TestClient, sample_sensors: list[Sensor], mock_sensor_repository: MagicMock, auth_headers: Dict[str, str]) -> None:
    # Setup mocks
    mock_repository_class.return_value = mock_sensor_repository
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    # Make request with auth headers
    response = client.get("/api/v1/campaigns/1/stations/1/sensors?description_contains=Temperature", headers=auth_headers)

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert "Temperature" in data["items"][0]["description"]
    return None


@patch('app.api.v1.routes.campaigns.campaign_station_sensors.SensorRepository')
@patch('app.core.config.get_settings')
def test_list_sensors_with_postprocess_filter(mock_get_settings: MagicMock, mock_repository_class: MagicMock, client: TestClient, sample_sensors: list[Sensor], mock_sensor_repository: MagicMock, auth_headers: Dict[str, str]) -> None:
    # Setup mocks
    mock_repository_class.return_value = mock_sensor_repository
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    # Make request with auth headers
    response = client.get("/api/v1/campaigns/1/stations/1/sensors?postprocess=true", headers=auth_headers)

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert all(item["postprocess"] is True for item in data["items"])
    return None

@patch('app.api.v1.routes.campaigns.campaign_station_sensors.SensorRepository')
@patch('app.core.config.get_settings')
def test_list_sensors_pagination(mock_get_settings: MagicMock, mock_repository_class: MagicMock, client: TestClient, sample_sensors: list[Sensor], mock_sensor_repository: MagicMock, auth_headers: Dict[str, str]) -> None:
    # Setup mocks
    mock_repository_class.return_value = mock_sensor_repository
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    # Test first page
    response = client.get("/api/v1/campaigns/1/stations/1/sensors?page=1&limit=2", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["size"] == 2
    assert data["pages"] == 2

    # Test second page
    response = client.get("/api/v1/campaigns/1/stations/1/sensors?page=2&limit=2", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["total"] == 3
    assert data["page"] == 2
    assert data["size"] == 2
    assert data["pages"] == 2

    return None

@patch('app.api.v1.routes.campaigns.campaign_station_sensors.SensorRepository')
@patch('app.core.config.get_settings')
def test_list_sensors_combined_filters(mock_get_settings: MagicMock, mock_repository_class: MagicMock, client: TestClient, sample_sensors: list[Sensor], mock_sensor_repository: MagicMock, auth_headers: Dict[str, str]) -> None:
    # Setup mocks
    mock_repository_class.return_value = mock_sensor_repository
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    # Make request with auth headers
    response = client.get(
        "/api/v1/campaigns/1/stations/1/sensors"
        "?variable_name=temp"
        "&units=°F"
        "&postprocess=true",
        headers=auth_headers
    )

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["variablename"] == "temperature"
    assert data["items"][0]["units"] == "°F"
    assert data["items"][0]["postprocess"] is True

@patch('app.api.v1.routes.campaigns.campaign_station_sensors.SensorRepository')
@patch('app.core.config.get_settings')
def test_list_sensors_unauthorized(mock_get_settings: MagicMock, mock_repository_class: MagicMock, client: TestClient) -> None:
    # Setup mocks
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    # Make request without auth headers
    response = client.get("/api/v1/campaigns/1/stations/1/sensors")

    # Verify response
    assert response.status_code == 401  # Unauthorized
    return None

@patch('app.api.v1.routes.campaigns.campaign_station_sensors.SensorRepository')
@patch('app.core.config.get_settings')
def test_list_sensors_sort_by_alias_asc(
    mock_get_settings: MagicMock,
    mock_repository_class: MagicMock,
    client: TestClient,
    sample_sensors: list[Sensor],
    mock_sensor_repository: MagicMock,
    auth_headers: Dict[str, str]
) -> None:
    # Setup mocks
    mock_repository_class.return_value = mock_sensor_repository
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    # Make request with auth headers
    response = client.get("/api/v1/campaigns/1/stations/1/sensors?sort_by=alias&sort_order=asc", headers=auth_headers)

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 3
    assert data["items"][0]["alias"] == "humidity_sensor"
    assert data["items"][1]["alias"] == "pressure_sensor"
    assert data["items"][2]["alias"] == "temp_sensor"

@patch('app.api.v1.routes.campaigns.campaign_station_sensors.SensorRepository')
@patch('app.core.config.get_settings')
def test_list_sensors_sort_by_alias_desc(
    mock_get_settings: MagicMock,
    mock_repository_class: MagicMock,
    client: TestClient,
    sample_sensors: list[Sensor],
    mock_sensor_repository: MagicMock,
    auth_headers: Dict[str, str]
) -> None:
    # Setup mocks
    mock_repository_class.return_value = mock_sensor_repository
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    # Make request with auth headers
    response = client.get("/api/v1/campaigns/1/stations/1/sensors?sort_by=alias&sort_order=desc", headers=auth_headers)

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 3
    assert data["items"][0]["alias"] == "temp_sensor"
    assert data["items"][1]["alias"] == "pressure_sensor"
    assert data["items"][2]["alias"] == "humidity_sensor"

@patch('app.api.v1.routes.campaigns.campaign_station_sensors.SensorRepository')
@patch('app.core.config.get_settings')
def test_list_sensors_sort_by_max_value(
    mock_get_settings: MagicMock,
    mock_repository_class: MagicMock,
    client: TestClient,
    sample_sensors: list[Sensor],
    mock_sensor_repository: MagicMock,
    auth_headers: Dict[str, str]
) -> None:
    # Setup mocks
    mock_repository_class.return_value = mock_sensor_repository
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    # Make request with auth headers
    response = client.get("/api/v1/campaigns/1/stations/1/sensors?sort_by=max_value&sort_order=desc", headers=auth_headers)

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 3
    # All sensors have the same max_value in our test data, so we just verify the structure
    assert all("statistics" in item for item in data["items"])
    assert all("max_value" in item["statistics"] for item in data["items"])

@patch('app.api.v1.routes.campaigns.campaign_station_sensors.SensorRepository')
@patch('app.core.config.get_settings')
def test_list_sensors_sort_with_filters(
    mock_get_settings: MagicMock,
    mock_repository_class: MagicMock,
    client: TestClient,
    sample_sensors: list[Sensor],
    mock_sensor_repository: MagicMock,
    auth_headers: Dict[str, str]
) -> None:
    # Setup mocks
    mock_repository_class.return_value = mock_sensor_repository
    mock_settings = MagicMock()
    mock_settings.JWT_SECRET = TEST_JWT_SECRET
    mock_settings.ALG = TEST_JWT_ALGORITHM
    mock_get_settings.return_value = mock_settings

    # Make request with auth headers
    response = client.get(
        "/api/v1/campaigns/1/stations/1/sensors"
        "?postprocess=true"
        "&sort_by=alias"
        "&sort_order=asc",
        headers=auth_headers
    )

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2  # Only postprocess=true sensors
    assert data["items"][0]["alias"] == "pressure_sensor"
    assert data["items"][1]["alias"] == "temp_sensor"
    assert all(item["postprocess"] is True for item in data["items"])