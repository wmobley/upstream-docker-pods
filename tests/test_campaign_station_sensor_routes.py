import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session

from app.main import app
from app.api.v1.schemas.sensor import (
    SensorUpdate,
    SensorCreateResponse,
    GetSensorResponse,
    SensorItem,
    SensorStatistics,
    ListSensorsResponsePagination
)
from app.api.v1.schemas.user import User
from app.api.dependencies.auth import get_current_user
from app.db.session import get_db
from app.db.repositories.sensor_repository import SortField

# Mock data for testing
MOCK_USER = User(
    id=1,
    username="testuser",
    email="test@example.com",
    is_active=True
)

MOCK_SENSOR_UPDATE_PAYLOAD = {
    "alias": "Temp Sensor A",
    "description": "Measures ambient temperature",
    "postprocess": False,
    "postprocessscript": None,
    "units": "Celsius",
    "variablename": "temperature"
}

MOCK_SENSOR_PARTIAL_UPDATE_PAYLOAD = {
    "description": "Updated description for temp sensor"
}

MOCK_SENSOR_CREATE_RESPONSE = {"id": 789}

MOCK_GET_SENSOR_RESPONSE_DATA = {
    "id": 789,
    "alias": "Temp Sensor A",
    "variablename": "temperature",
    "description": "Measures ambient temperature",
    "postprocess": False,
    "postprocessscript": None,
    "units": "Celsius",
    "statistics": None
}

MOCK_SENSOR_ITEM_DATA = {
    "id": 789,
    "alias": "Temp Sensor A",
    "variablename": "temperature",
    "description": "Measures ambient temperature",
    "postprocess": False,
    "postprocessscript": None,
    "units": "Celsius",
    "statistics": None
}


def override_get_current_user():
    return MOCK_USER


def override_get_db():
    return Mock(spec=Session)


@pytest.fixture
def client_with_auth():
    with patch.dict('os.environ', {
        'DATABASE_URL': 'sqlite:///:memory:',
        'SECRET_KEY': 'test-secret-key',
    }):
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        yield client
        app.dependency_overrides.clear()


@pytest.fixture
def client_no_auth():
    with patch.dict('os.environ', {
        'DATABASE_URL': 'sqlite:///:memory:',
        'SECRET_KEY': 'test-secret-key',
    }):
        client = TestClient(app)
        yield client
        app.dependency_overrides.clear()


class TestCampaignStationSensorRoutes:
    campaign_id = 1
    station_id = 123
    sensor_id = 789

    # GET /campaigns/{campaign_id}/stations/{station_id}/sensors
    def test_list_sensors_success(self, client_with_auth):
        mock_items = [SensorItem(**MOCK_SENSOR_ITEM_DATA)]
        with patch('app.api.v1.routes.campaigns.campaign_station_sensors.check_allocation_permission', return_value=True), \
             patch('app.services.sensor_service.SensorService.get_sensors_by_station_id') as mock_list:
            mock_list.return_value = (mock_items, 1)
            response = client_with_auth.get(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/sensors?page=1&limit=10&sort_by={SortField.ALIAS.value}&sort_order=desc"
            )
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 1
            assert len(data["items"]) == 1
            assert data["items"][0]["id"] == MOCK_SENSOR_ITEM_DATA["id"]
            mock_list.assert_called_once_with(
                station_id=self.station_id,
                page=1,
                limit=10,
                variable_name=None,
                units=None,
                alias=None,
                description_contains=None,
                postprocess=None,
                sort_by=SortField.ALIAS,
                sort_order="desc"
            )

    def test_list_sensors_permission_denied(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_station_sensors.check_allocation_permission', return_value=False):
            response = client_with_auth.get(f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/sensors")
            assert response.status_code == 404
            assert response.json()["detail"] == "Allocation is incorrect"

    def test_list_sensors_unauthorized(self, client_no_auth):
        response = client_no_auth.get(f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/sensors")
        assert response.status_code == 401

    # GET /campaigns/{campaign_id}/stations/{station_id}/sensors/{sensor_id}
    def test_get_sensor_success(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_station_sensors.check_allocation_permission', return_value=True), \
             patch('app.services.sensor_service.SensorService.get_sensor') as mock_get:
            mock_get.return_value = GetSensorResponse(**MOCK_GET_SENSOR_RESPONSE_DATA)
            response = client_with_auth.get(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/sensors/{self.sensor_id}"
            )
            assert response.status_code == 200
            assert response.json()["id"] == self.sensor_id
            mock_get.assert_called_once_with(self.sensor_id)

    def test_get_sensor_not_found(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_station_sensors.check_allocation_permission', return_value=True), \
             patch('app.services.sensor_service.SensorService.get_sensor', return_value=None) as mock_get:
            response = client_with_auth.get(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/sensors/{self.sensor_id}"
            )
            assert response.status_code == 404
            assert response.json()["detail"] == "Sensor not found"
            mock_get.assert_called_once_with(self.sensor_id)

    # DELETE /campaigns/{campaign_id}/stations/{station_id}/sensors
    # Note: The route function is named delete_sensor, but it deletes all sensors for a station.
    def test_delete_station_sensors_success(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_station_sensors.check_allocation_permission', return_value=True), \
             patch('app.services.station_service.StationService.delete_station_sensors') as mock_delete:
            response = client_with_auth.delete(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/sensors"
            )
            assert response.status_code == 204
            mock_delete.assert_called_once_with(station_id=self.station_id)

    def test_delete_station_sensors_permission_denied(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_station_sensors.check_allocation_permission', return_value=False):
            response = client_with_auth.delete(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/sensors"
            )
            assert response.status_code == 404
            assert response.json()["detail"] == "Allocation is incorrect"

    # PUT /campaigns/{campaign_id}/stations/{station_id}/sensors/{sensor_id}
    def test_update_sensor_success(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_station_sensors.check_allocation_permission', return_value=True), \
             patch('app.services.sensor_service.SensorService.update_sensor') as mock_update:
            mock_update.return_value = SensorCreateResponse(**MOCK_SENSOR_CREATE_RESPONSE)
            response = client_with_auth.put(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/sensors/{self.sensor_id}",
                json=MOCK_SENSOR_UPDATE_PAYLOAD
            )
            assert response.status_code == 200
            assert response.json()["id"] == MOCK_SENSOR_CREATE_RESPONSE["id"]
            mock_update.assert_called_once()
            called_arg_sensor_id, called_arg_sensor_data = mock_update.call_args[0]
            assert called_arg_sensor_id == self.sensor_id
            assert isinstance(called_arg_sensor_data, SensorUpdate)
            assert called_arg_sensor_data.alias == MOCK_SENSOR_UPDATE_PAYLOAD["alias"]

    def test_update_sensor_not_found(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_station_sensors.check_allocation_permission', return_value=True), \
             patch('app.services.sensor_service.SensorService.update_sensor', return_value=None):
            response = client_with_auth.put(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/sensors/{self.sensor_id}",
                json=MOCK_SENSOR_UPDATE_PAYLOAD
            )
            assert response.status_code == 404
            # The route actually says "Station not found", but it's a sensor update.
            # This could be a point of improvement in the route's error message.
            assert response.json()["detail"] == "Station not found"

    def test_update_sensor_invalid_data(self, client_with_auth):
        invalid_payload = MOCK_SENSOR_UPDATE_PAYLOAD.copy()
        invalid_payload["postprocess"] = "not-a-boolean"
        with patch('app.api.v1.routes.campaigns.campaign_station_sensors.check_allocation_permission', return_value=True):
            response = client_with_auth.put(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/sensors/{self.sensor_id}",
                json=invalid_payload
            )
            assert response.status_code == 422

    # PATCH /campaigns/{campaign_id}/stations/{station_id}/sensors/{sensor_id}
    def test_partial_update_sensor_success(self, client_with_auth):
        # Assuming SensorUpdate schema has all fields optional for PATCH
        with patch('app.api.v1.routes.campaigns.campaign_station_sensors.check_allocation_permission', return_value=True), \
             patch('app.services.sensor_service.SensorService.partial_update_sensor') as mock_partial_update:
            mock_partial_update.return_value = SensorCreateResponse(**MOCK_SENSOR_CREATE_RESPONSE)
            response = client_with_auth.patch(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/sensors/{self.sensor_id}",
                json=MOCK_SENSOR_PARTIAL_UPDATE_PAYLOAD
            )
            assert response.status_code == 200
            assert response.json()["id"] == MOCK_SENSOR_CREATE_RESPONSE["id"]
            mock_partial_update.assert_called_once()
            called_arg_sensor_id, called_arg_sensor_data = mock_partial_update.call_args[0]
            assert called_arg_sensor_id == self.sensor_id
            assert isinstance(called_arg_sensor_data, SensorUpdate)
            assert called_arg_sensor_data.description == MOCK_SENSOR_PARTIAL_UPDATE_PAYLOAD["description"]

    def test_partial_update_sensor_not_found(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_station_sensors.check_allocation_permission', return_value=True), \
             patch('app.services.sensor_service.SensorService.partial_update_sensor', return_value=None):
            response = client_with_auth.patch(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/sensors/{self.sensor_id}",
                json=MOCK_SENSOR_PARTIAL_UPDATE_PAYLOAD
            )
            assert response.status_code == 404
            assert response.json()["detail"] == "Station not found" # Same note as update_sensor

    def test_partial_update_sensor_empty_body(self, client_with_auth):
        # This test assumes SensorUpdate allows empty bodies for PATCH if all fields are optional.
        # If SensorUpdate has required fields even for PATCH, this might return 422.
        with patch('app.api.v1.routes.campaigns.campaign_station_sensors.check_allocation_permission', return_value=True), \
             patch('app.services.sensor_service.SensorService.partial_update_sensor') as mock_partial_update:
            mock_partial_update.return_value = SensorCreateResponse(**MOCK_SENSOR_CREATE_RESPONSE)
            response = client_with_auth.patch(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/sensors/{self.sensor_id}",
                json={}
            )
            # If SensorUpdate has all Optional fields, this should be 200.
            # If not, it might be 422. Adjust based on your SensorUpdate schema.
            assert response.status_code == 200 # or 422 if SensorUpdate is not fully optional
            if response.status_code == 200:
                assert response.json()["id"] == MOCK_SENSOR_CREATE_RESPONSE["id"]
                mock_partial_update.assert_called_once()
                _, called_arg_sensor_data = mock_partial_update.call_args[0]
                assert called_arg_sensor_data.model_dump(exclude_unset=True) == {}

    def test_partial_update_sensor_invalid_data_type(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_station_sensors.check_allocation_permission', return_value=True):
            response = client_with_auth.patch(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/sensors/{self.sensor_id}",
                json={"postprocess": "not-a-boolean"}
            )
            assert response.status_code == 422