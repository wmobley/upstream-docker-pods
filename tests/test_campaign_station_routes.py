import pytest
from datetime import datetime
from fastapi import HTTPException
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session

from app.main import app
from app.api.v1.schemas.station import (
    StationCreate,
    StationUpdate,
    StationCreateResponse,
    GetStationResponse,
    StationItemWithSummary,
    StationsListResponseItem,
)
from app.api.v1.schemas.campaign import GetCampaignResponse, PublishResponse, SummaryGetCampaign
from app.api.v1.schemas.user import User
from app.api.dependencies import auth
from app.api.dependencies.auth import get_current_user, get_edit_user
from app.api.dependencies.ckan import get_user_allocations
from app.db.session import get_db
from app.services.ckan_publish import build_station_dataset_identity

# Mock data for testing
MOCK_USER = User(
    id=1,
    username="testuser",
    email="test@example.com",
    is_active=True,
    role="ADMIN",
)

MOCK_STATION_CREATE_PAYLOAD = {
    "name": "Test Station Alpha",
    "description": "A station for testing purposes",
    "contact_name": "Dr. Test",
    "contact_email": "dr.test@example.com",
    "active": True,
    "start_date": "2024-01-15T10:00:00",
    "station_type": "static",
    "timezone": "America/Chicago",
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
    "timezone": "America/Chicago",
    "geometry": {},
    "sensors": []
}

MOCK_STATION_ITEM_SUMMARY = {
    "id": 123,
    "name": "Test Station Alpha",
    "description": "A station for testing purposes",
    "geometry": {},
    "timezone": "America/Chicago",
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
        app.dependency_overrides[get_edit_user] = override_get_current_user
        app.dependency_overrides[get_user_allocations] = lambda: ["test-allocation"]
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
        auth.settings.ENV = "test"
        app.dependency_overrides[get_db] = override_get_db
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

    def test_delete_station_success(self, client_with_auth):
        campaign_response = GetCampaignResponse(
            id=self.campaign_id,
            name="Test Campaign",
            summary=SummaryGetCampaign(
                station_count=1,
                sensor_count=0,
                sensor_types=[],
                sensor_variables=[],
            ),
            stations=[
                StationsListResponseItem(
                    id=self.station_id,
                    name="Test Station Alpha",
                    description="Test description",
                    start_date=datetime.utcnow(),
                    timezone="America/Chicago",
                )
            ],
        )
        station_response = GetStationResponse(
            id=self.station_id,
            name="Test Station Alpha",
            description="Test description",
            start_date=datetime.utcnow(),
            timezone="America/Chicago",
            geometry={},
            sensors=[],
        )

        mock_settings = Mock()
        mock_settings.CKAN_URL = "https://ckan.example.com"
        mock_settings.UI_BASE_URL = "https://ui.example.com"

        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.get_campaign_with_summary', return_value=campaign_response) as mock_get_campaign, \
             patch('app.services.station_service.StationService.get_station', return_value=station_response) as mock_get_station, \
             patch('app.services.station_service.StationService.delete_station_sensors') as mock_delete_sensors, \
             patch('app.services.station_service.StationService.delete_station', return_value=True) as mock_delete_station, \
             patch('app.api.v1.routes.campaigns.campaign_stations.get_ckan_service') as mock_get_ckan_service, \
             patch('app.api.v1.routes.campaigns.campaign_stations.get_settings', return_value=mock_settings):
            mock_ckan_client = Mock()
            mock_get_ckan_service.return_value = mock_ckan_client

            response = client_with_auth.delete(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}",
                headers={"X-TAPIS-TOKEN": "fake-token"},
            )

            assert response.status_code == 204
            mock_get_campaign.assert_called_once_with(self.campaign_id)
            mock_get_station.assert_called_once_with(self.station_id)
            mock_delete_sensors.assert_called_once_with(station_id=self.station_id)
            mock_delete_station.assert_called_once_with(self.station_id)

            expected_slug = build_station_dataset_identity(
                settings=mock_settings,
                campaign=campaign_response,
                station=station_response,
            )["name"]
            mock_ckan_client.delete_dataset.assert_called_once_with(
                token="fake-token",
                name_or_id=expected_slug,
            )

    def test_delete_station_not_in_campaign(self, client_with_auth):
        campaign_response = GetCampaignResponse(
            id=self.campaign_id,
            name="Test Campaign",
            summary=SummaryGetCampaign(
                station_count=0,
                sensor_count=0,
                sensor_types=[],
                sensor_variables=[],
            ),
            stations=[],
        )
        station_response = GetStationResponse(
            id=self.station_id,
            name="Orphan Station",
            description="Test description",
            start_date=datetime.utcnow(),
            timezone="America/Chicago",
            geometry={},
            sensors=[],
        )

        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.get_campaign_with_summary', return_value=campaign_response), \
             patch('app.services.station_service.StationService.get_station', return_value=station_response), \
             patch('app.services.station_service.StationService.delete_station_sensors') as mock_delete_sensors, \
             patch('app.services.station_service.StationService.delete_station') as mock_delete_station:
            response = client_with_auth.delete(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}",
                headers={"X-TAPIS-TOKEN": "fake-token"},
            )

            assert response.status_code == 404
            assert response.json()["detail"] == "Station not found"
            mock_delete_sensors.assert_not_called()
            mock_delete_station.assert_not_called()

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

    def test_publish_station_returns_application_failure_when_ckan_membership_missing(self, client_with_auth):
        campaign_response = GetCampaignResponse(
            id=self.campaign_id,
            name="Test Campaign",
            allocation="restricted-org",
            summary=SummaryGetCampaign(
                station_count=1,
                sensor_count=0,
                sensor_types=[],
                sensor_variables=[],
            ),
            stations=[],
        )
        station_response = GetStationResponse(
            id=self.station_id,
            name="Test Station Alpha",
            description="Test description",
            start_date=datetime.utcnow(),
            timezone="America/Chicago",
            geometry={},
            sensors=[],
        )

        mock_settings = Mock()
        mock_settings.CKAN_URL = "https://ckan.example.com"
        mock_settings.CKAN_ORGANIZATION = None

        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True), \
             patch('app.services.station_service.StationService.get_station', return_value=station_response), \
             patch('app.services.campaign_service.CampaignService.get_campaign_with_summary', return_value=campaign_response), \
             patch('app.api.v1.routes.campaigns.campaign_stations.get_settings', return_value=mock_settings), \
             patch('app.api.v1.routes.campaigns.campaign_stations.get_ckan_service') as mock_get_ckan_service, \
             patch('app.services.station_service.StationService.set_publish_state') as mock_set_publish_state:
            mock_ckan_client = Mock()
            mock_ckan_client.list_user_organizations.return_value = []
            mock_get_ckan_service.return_value = mock_ckan_client

            response = client_with_auth.post(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/publish",
                json={"cascade": False},
                headers={"X-TAPIS-TOKEN": "fake-token", "X-Request-ID": "req-station-failure"},
            )

            assert response.status_code == 200
            body = response.json()
            assert body["success"] is False
            assert body["is_published"] is False
            assert "not published due to CKAN errors" in body["message"]
            assert body["errors"]
            mock_set_publish_state.assert_not_called()

    def test_publish_station_passes_ckan_conflict_options(self, client_with_auth):
        campaign_response = GetCampaignResponse(
            id=self.campaign_id,
            name="Test Campaign",
            allocation="restricted-org",
            summary=SummaryGetCampaign(
                station_count=1,
                sensor_count=0,
                sensor_types=[],
                sensor_variables=[],
            ),
            stations=[],
        )
        station_response = GetStationResponse(
            id=self.station_id,
            name="Test Station Alpha",
            description="Test description",
            start_date=datetime.utcnow(),
            timezone="America/Chicago",
            geometry={},
            sensors=[],
        )

        mock_settings = Mock()
        mock_settings.CKAN_URL = "https://ckan.example.com"
        mock_settings.CKAN_ORGANIZATION = None
        mock_settings.UI_BASE_URL = "https://ui.example.com"
        mock_settings.API_BASE_URL = "https://api.example.com"

        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True), \
             patch('app.services.station_service.StationService.get_station', return_value=station_response), \
             patch('app.services.campaign_service.CampaignService.get_campaign_with_summary', return_value=campaign_response), \
             patch('app.api.v1.routes.campaigns.campaign_stations.get_settings', return_value=mock_settings), \
             patch('app.api.v1.routes.campaigns.campaign_stations.get_ckan_service') as mock_get_ckan_service, \
             patch('app.db.repositories.metadata_schema_repository.MetadataSchemaRepository.list_schema', return_value=[]), \
             patch('app.api.v1.routes.campaigns.campaign_stations.ensure_station_dataset') as mock_ensure_dataset, \
             patch('app.api.v1.routes.campaigns.campaign_stations.sync_sensor_resources', return_value=[]), \
             patch('app.services.station_service.StationService.set_publish_state', return_value=True):
            mock_ckan_client = Mock()
            mock_ckan_client.list_user_organizations.return_value = [{"name": "restricted-org"}]
            mock_get_ckan_service.return_value = mock_ckan_client
            mock_ensure_dataset.return_value = (
                {"id": "dataset-1", "name": "custom-dataset-name", "resources": []},
                "dataset-1",
                [],
            )

            response = client_with_auth.post(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}/publish",
                json={
                    "cascade": False,
                    "ckan_dataset_name": "Custom Dataset Name",
                    "patch_existing_ckan_dataset": True,
                },
                headers={"X-TAPIS-TOKEN": "fake-token", "X-Request-ID": "req-station-options"},
            )

            assert response.status_code == 200
            assert response.json()["success"] is True
            kwargs = mock_ensure_dataset.call_args.kwargs
            assert kwargs["dataset_name"] == "Custom Dataset Name"
            assert kwargs["allow_existing_patch"] is True

    def test_publish_campaign_returns_child_station_errors(self, client_with_auth):
        campaign_response = GetCampaignResponse(
            id=self.campaign_id,
            name="Test Campaign",
            summary=SummaryGetCampaign(
                station_count=2,
                sensor_count=0,
                sensor_types=[],
                sensor_variables=[],
            ),
            stations=[],
        )
        station_one = Mock(stationid=101)
        station_two = Mock(stationid=102)

        with patch('app.api.v1.routes.campaigns.root.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.get_campaign_with_summary', return_value=campaign_response), \
             patch('app.db.repositories.station_repository.StationRepository.get_stations_by_campaign_id', return_value=[station_one, station_two]), \
             patch('app.api.v1.routes.campaigns.campaign_stations.publish_station', autospec=True) as mock_publish_station:
            mock_publish_station.side_effect = [
                PublishResponse(
                    success=True,
                    message="ok",
                    published_count=1,
                    errors=[],
                    id=101,
                    type="station",
                    is_published=True,
                    cascaded_items=[],
                ),
                HTTPException(status_code=502, detail="CKAN dataset sync failed"),
            ]

            response = client_with_auth.post(
                f"/api/v1/campaigns/{self.campaign_id}/publish",
                json={"cascade": True},
                headers={"X-TAPIS-TOKEN": "fake-token", "X-Request-ID": "req-campaign-failure"},
            )

            assert response.status_code == 200
            body = response.json()
            assert body["success"] is False
            assert body["is_published"] is True
            assert "published with some errors" in body["message"]
            assert "station 102: CKAN dataset sync failed" in body["errors"]

    def test_publish_campaign_returns_child_station_application_errors(self, client_with_auth):
        campaign_response = GetCampaignResponse(
            id=self.campaign_id,
            name="Test Campaign",
            summary=SummaryGetCampaign(
                station_count=1,
                sensor_count=0,
                sensor_types=[],
                sensor_variables=[],
            ),
            stations=[],
        )
        station_one = Mock(stationid=101)

        with patch('app.api.v1.routes.campaigns.root.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.get_campaign_with_summary', return_value=campaign_response), \
             patch('app.db.repositories.station_repository.StationRepository.get_stations_by_campaign_id', return_value=[station_one]), \
             patch('app.api.v1.routes.campaigns.campaign_stations.publish_station', autospec=True) as mock_publish_station:
            mock_publish_station.return_value = PublishResponse(
                success=False,
                message="Station not published due to CKAN errors",
                published_count=0,
                errors=["CKAN dataset sync failed"],
                id=101,
                type="station",
                is_published=False,
                cascaded_items=[],
            )

            response = client_with_auth.post(
                f"/api/v1/campaigns/{self.campaign_id}/publish",
                json={"cascade": True, "patch_existing_ckan_dataset": True},
                headers={"X-TAPIS-TOKEN": "fake-token", "X-Request-ID": "req-campaign-app-failure"},
            )

            assert response.status_code == 200
            body = response.json()
            assert body["success"] is False
            assert "station 101: CKAN dataset sync failed" in body["errors"]
            assert "station:101" not in body["cascaded_items"]
            delegated_request = mock_publish_station.call_args.kwargs["publish_request"]
            assert delegated_request.patch_existing_ckan_dataset is True

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

    def test_create_station_missing_timezone(self, client_with_auth):
        payload_missing_timezone = MOCK_STATION_CREATE_PAYLOAD.copy()
        del payload_missing_timezone["timezone"]  # timezone is required by StationCreate
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True):
            response = client_with_auth.post(
                f"/api/v1/campaigns/{self.campaign_id}/stations", json=payload_missing_timezone
            )
            assert response.status_code == 422

    def test_create_station_invalid_timezone(self, client_with_auth):
        payload_invalid_timezone = MOCK_STATION_CREATE_PAYLOAD.copy()
        payload_invalid_timezone["timezone"] = "Not/AZone"
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True):
            response = client_with_auth.post(
                f"/api/v1/campaigns/{self.campaign_id}/stations", json=payload_invalid_timezone
            )
            assert response.status_code == 422

    def test_update_station_invalid_timezone(self, client_with_auth):
        payload_invalid_timezone = MOCK_STATION_UPDATE_PAYLOAD.copy()
        payload_invalid_timezone["timezone"] = "Not/AZone"
        with patch('app.api.v1.routes.campaigns.campaign_stations.check_allocation_permission', return_value=True):
            response = client_with_auth.put(
                f"/api/v1/campaigns/{self.campaign_id}/stations/{self.station_id}",
                json=payload_invalid_timezone,
            )
            assert response.status_code == 422


class TestCampaignDetailIncludesStationTimezone:
    """Regression: GET /campaigns/{id} builds station items that must include
    timezone (added as a required field). Missing it raised a 500
    ValidationError that surfaced as a CORS error in the browser."""

    def _mock_station(self, stationid, stationname, timezone):
        st = Mock()
        st.stationid = stationid
        st.stationname = stationname
        st.description = "d"
        st.contactname = "c"
        st.contactemail = "e"
        st.active = True
        st.startdate = datetime(2024, 1, 1)
        st.timezone = timezone
        st.published = False
        st.published_at = None
        st.geometry = None
        st.meta = None
        st.sensors = []
        return st

    def _mock_campaign(self, stations):
        c = Mock()
        c.campaignid = 1
        c.campaignname = "C"
        c.description = "d"
        c.contactname = "c"
        c.contactemail = "e"
        c.startdate = datetime(2024, 1, 1)
        c.enddate = datetime(2024, 12, 31)
        c.allocation = "A"
        c.bbox_west = c.bbox_east = c.bbox_south = c.bbox_north = 0.0
        c.geometry = None
        c.meta = None
        c.stations = stations
        return c

    def test_campaign_detail_stations_include_timezone(self):
        from app.services.campaign_service import CampaignService

        repo = Mock()
        repo.get_campaign.return_value = self._mock_campaign(
            [
                self._mock_station(1, "S1", "America/Chicago"),
                self._mock_station(2, "S2", "UTC"),
            ]
        )
        repo.count_stations.return_value = 2
        repo.count_sensors.return_value = 0
        repo.get_sensor_types.return_value = []
        repo.get_sensor_variables.return_value = []

        result = CampaignService(repo).get_campaign_with_summary(1)

        assert [s.timezone for s in result.stations] == ["America/Chicago", "UTC"]
