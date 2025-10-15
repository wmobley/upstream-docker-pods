import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session

from app.main import app
from app.api.v1.schemas.station import StationCreate, StationUpdate, StationCreateResponse, GetStationResponse, StationItemWithSummary
from app.api.v1.schemas.user import User
from app.api.dependencies.auth import get_current_user
from app.db.session import get_db

# Mock data for testing
MOCK_USER = User(
    id=1,
    username="testuser",
    email="test@example.com",
    is_active=True
)

MOCK_STATION_CREATE_PAYLOAD = {
    "name": "Test Station Alpha",
    "description": "A station for testing purposes",
    "contact_name": "Dr. Test",
    "contact_email": "dr.test@example.com",
    "active": True,
    "start_date": "2024-01-15T10:00:00",
    "station_type": "static"
}

MOCK_STATION_UPDATE_PAYLOAD = {
    "name": "Updated Test Station Alpha",
    "description": "An updated station for testing",
    "contact_name": "Prof. Test",
    "contact_email": "prof.test@example.com",
    "active": False,
    "start_date": "2024-02-20T11:00:00",
    "station_type": "mobile"
}

MOCK_STATION_PARTIAL_UPDATE_PAYLOAD = {
    "description": "Partially updated description"
}

MOCK_STATION_CREATE_RESPONSE = {"id": 123}

MOCK_GET_STATION_RESPONSE = {
    "id": 123,
    "name": "Test Station Alpha",
    "description": "A station for testing purposes",
    "contact_name": "Dr. Test",
    "contact_email": "dr.test@example.com",
    "active": True,
    "start_date": "2024-01-15T10:00:00Z", # Assuming timezone info might be added
    "geometry": {},
    "sensors": []
}

MOCK_STATION_ITEM_SUMMARY = {
    "id": 123,
    "name": "Test Station Alpha",
    "description": "A station for testing purposes",
    "geometry": {},
    "sensor_types": ["temperature"],
    "sensor_variables": ["temp_celsius"],
    "sensor_count": 1
}


def override_get_current_user():
    return MOCK_USER


def override_get_db():
    return Mock(spec=Session)


@pytest.fixture
def client_with_auth():
    with patch.dict('os.environ', {
        'DATABASE_URL': 'sqlite:///:memory:', # Ensure tests run in a controlled env
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


class TestCampaignStationRoutes:
    campaign_id = 1
    station_id = 123

    # POST /campaigns/{campaign_id}/stations
    def test_create_station_success(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True), \
             patch('app.services.station_service.StationService.create_station') as mock_create:
            mock_create.return_value = StationCreateResponse(**MOCK_STATION_CREATE_RESPONSE)
            response = client_with_auth.post(f"/api/v1/campaigns/{self.campaign_id}/stations", json=MOCK_STATION_CREATE_PAYLOAD)
            assert response.status_code == 200
            assert response.json() == MOCK_STATION_CREATE_RESPONSE
            mock_create.assert_called_once()
            called_arg_station, called_arg_campaign_id = mock_create.call_args[0]
            assert isinstance(called_arg_station, StationCreate)
            assert called_arg_station.name == MOCK_STATION_CREATE_PAYLOAD["name"]
            assert called_arg_campaign_id == self.campaign_id

    def test_create_station_permission_denied(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=False):
            response = client_with_auth.post(f"/api/v1/campaigns/{self.campaign_id}/stations", json=MOCK_STATION_CREATE_PAYLOAD)
            assert response.status_code == 404
            assert response.json()["detail"] == "Allocation is incorrect"

    def test_create_station_unauthorized(self, client_no_auth):
        response = client_no_auth.post(f"/api/v1/campaigns/{self.campaign_id}/stations", json=MOCK_STATION_CREATE_PAYLOAD)
        assert response.status_code == 401

    # GET /campaigns/{campaign_id}/stations
    def test_list_stations_success(self, client_with_auth):
        mock_items = [StationItemWithSummary(**MOCK_STATION_ITEM_SUMMARY)]
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True), \
             patch('app.services.station_service.StationService.get_stations_with_summary') as mock_list:
            mock_list.return_value = (mock_items, 1)
            response = client_with_auth.get(f"/api/v1/campaigns/{self.campaign_id}/stations")
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 1
            assert len(data["items"]) == 1
            assert data["items"][0]["id"] == MOCK_STATION_ITEM_SUMMARY["id"]
            mock_list.assert_called_once_with(self.campaign_id, 1, 20)

    def test_list_stations_permission_denied(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=False):
            response = client_with_auth.get(f"/api/v1/campaigns/{self.campaign_id}/stations")
            assert response.status_code == 404
            assert response.json()["detail"] == "Allocation is incorrect"

    # GET /campaigns/{campaign_id}/stations/{station_id}
    def test_get_station_success(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True), \
             patch('app.services.station_service.StationService.get_station') as mock_get:
            mock_get.return_value = GetStationResponse(**MOCK_GET_STATION_RESPONSE)
            response = client_with_auth.get(f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}")
            assert response.status_code == 200
            assert response.json()["id"] == self.station_id
            mock_get.assert_called_once_with(self.station_id)

    def test_get_station_not_found(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True), \
             patch('app.services.station_service.StationService.get_station', return_value=None) as mock_get:
            response = client_with_auth.get(f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}")
            assert response.status_code == 404
            assert response.json()["detail"] == "Station not found"
            mock_get.assert_called_once_with(self.station_id)

    # DELETE /campaigns/{campaign_id}/stations
    # Note: The route function is named delete_sensor, but it deletes campaign stations.
    def test_delete_campaign_stations_success(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.delete_campaign_station') as mock_delete:
            mock_delete.return_value = True # Assuming it returns bool
            response = client_with_auth.delete(f"/api/v1/campaigns/{self.campaign_id}/stations")
            assert response.status_code == 204
            mock_delete.assert_called_once_with(campaign_id=self.campaign_id)

    def test_delete_campaign_stations_permission_denied(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=False):
            response = client_with_auth.delete(f"/api/v1/campaigns/{self.campaign_id}/stations")
            assert response.status_code == 404
            assert response.json()["detail"] == "Allocation is incorrect"

    # PUT /campaigns/{campaign_id}/stations/{station_id}
    def test_update_station_success(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True), \
             patch('app.services.station_service.StationService.update_station') as mock_update:
            mock_update.return_value = StationCreateResponse(id=self.station_id)
            response = client_with_auth.put(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}",
                json=MOCK_STATION_UPDATE_PAYLOAD
            )
            assert response.status_code == 200
            assert response.json()["id"] == self.station_id
            mock_update.assert_called_once()
            called_arg_station_id, called_arg_station_data = mock_update.call_args[0]
            assert called_arg_station_id == self.station_id
            assert isinstance(called_arg_station_data, StationUpdate)
            assert called_arg_station_data.name == MOCK_STATION_UPDATE_PAYLOAD["name"]

    def test_update_station_not_found_error_message(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True), \
             patch('app.services.station_service.StationService.update_station', return_value=None):
            response = client_with_auth.put(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}",
                json=MOCK_STATION_UPDATE_PAYLOAD
            )
            assert response.status_code == 404
            assert response.json()["detail"] == "Station not found"

    # PATCH /campaigns/{campaign_id}/stations/{station_id}
    # NOTE: The following PATCH tests are likely failing with 422 (Unprocessable Entity)
    # because the `StationUpdate` Pydantic model (in app/api/v1/schemas/station.py)
    # may have required fields. For PATCH to work with partial data or empty bodies,
    # all fields in `StationUpdate` should be `Optional`.
    def test_partial_update_station_success(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True), \
             patch('app.services.station_service.StationService.partial_update_station') as mock_partial_update:
            mock_partial_update.return_value = StationCreateResponse(id=self.station_id)
            response = client_with_auth.patch(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}",
                json=MOCK_STATION_PARTIAL_UPDATE_PAYLOAD
            )
            assert response.status_code == 200
            assert response.json()["id"] == self.station_id
            mock_partial_update.assert_called_once()
            called_arg_station_id, called_arg_station_data = mock_partial_update.call_args[0]
            assert called_arg_station_id == self.station_id
            assert isinstance(called_arg_station_data, StationUpdate)
            assert called_arg_station_data.description == MOCK_STATION_PARTIAL_UPDATE_PAYLOAD["description"]

    def test_partial_update_station_not_found_error_message(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True), \
             patch('app.services.station_service.StationService.partial_update_station', return_value=None):
            response = client_with_auth.patch(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}",
                json=MOCK_STATION_PARTIAL_UPDATE_PAYLOAD
            )
            assert response.status_code == 404
            assert response.json()["detail"] == "Station not found"

    def test_partial_update_station_empty_body(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True), \
             patch('app.services.station_service.StationService.partial_update_station') as mock_partial_update:
            mock_partial_update.return_value = StationCreateResponse(id=self.station_id)
            response = client_with_auth.patch(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}",
                json={}
            )
            assert response.status_code == 200
            assert response.json()["id"] == self.station_id
            mock_partial_update.assert_called_once()
            called_arg_station_id, called_arg_station_data = mock_partial_update.call_args[0]
            assert called_arg_station_data.model_dump(exclude_unset=True) == {}

    def test_partial_update_station_invalid_data_type(self, client_with_auth):
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True):
            response = client_with_auth.patch(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}",
                json={"active": "not-a-boolean"}
            )
            assert response.status_code == 422 # Pydantic validation error

    def test_update_station_invalid_data_type(self, client_with_auth):
        payload_with_invalid_type = MOCK_STATION_UPDATE_PAYLOAD.copy()
        payload_with_invalid_type["active"] = "not-a-boolean"
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True):
            response = client_with_auth.put(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}",
                json=payload_with_invalid_type
            )
            assert response.status_code == 422

    def test_create_station_missing_required_field(self, client_with_auth):
        payload_missing_field = MOCK_STATION_CREATE_PAYLOAD.copy()
        del payload_missing_field["name"] # 'name' is required by StationCreate
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True):
            response = client_with_auth.post(f"/api/v1/campaigns/{self.campaign_id}/stations", json=payload_missing_field)
            assert response.status_code == 422