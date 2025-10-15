import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session

from app.main import app
from app.api.v1.schemas.campaign import CampaignsIn, CampaignUpdate, CampaignCreateResponse
from app.api.v1.schemas.user import User
from app.db.models.campaign import Campaign
from app.api.dependencies.auth import get_current_user
from app.db.session import get_db

# Mock data for testing
MOCK_CAMPAIGN_DATA = {
    "id": 3,
    "name": "Test Campaign",
    "description": "Test Description",
    "contact_name": "John Doe",
    "contact_email": "john@example.com",
    "allocation": "TEST-123",
    "start_date": "2024-01-01T00:00:00",
    "end_date": "2024-12-31T00:00:00"
}

MOCK_CAMPAIGN_UPDATE = {
    "name": "Updated Campaign",
    "description": "Updated Description",
    "contact_name": "Jane Smith",
    "contact_email": "jane@example.com",
    "allocation": "UPDATED-123",
    "start_date": "2024-02-01T00:00:00",
    "end_date": "2024-11-30T00:00:00"
}

MOCK_PARTIAL_UPDATE = {
    "name": "Partially Updated Campaign",
    "description": "Partially Updated Description"
}

MOCK_USER = User(
    id=1,
    username="testuser",
    email="test@example.com",
    is_active=True
)


def override_get_current_user():
    return MOCK_USER


def override_get_db():
    return Mock(spec=Session)


@pytest.fixture
def client_with_auth():
    """Client with successful authentication and permissions"""
    with patch.dict('os.environ', {
        'DATABASE_URL': 'sqlite:///:memory:',
        'SECRET_KEY': 'test-secret-key',
    }):
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_db] = override_get_db
        
        client = TestClient(app)
        yield client
        
        # Clean up
        app.dependency_overrides.clear()


@pytest.fixture
def client_no_auth():
    """Client without authentication"""
    with patch.dict('os.environ', {
        'DATABASE_URL': 'sqlite:///:memory:',
        'SECRET_KEY': 'test-secret-key',
    }):
        client = TestClient(app)
        yield client


class TestCampaignPutRoute:
    """Tests for PUT /campaigns/{campaign_id}"""

    def test_put_campaign_success(self, client_with_auth):
        """Test successful campaign update via PUT"""
        campaign_id = 3
        
        with patch('app.api.dependencies.pytas.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.update_campaign') as mock_update:
            
            mock_update.return_value = CampaignCreateResponse(id=campaign_id)
            
            response = client_with_auth.put(f"/api/v1/campaigns/{campaign_id}", json=MOCK_CAMPAIGN_UPDATE)
            
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["id"] == campaign_id
            mock_update.assert_called_once()

    def test_put_campaign_permission_denied(self, client_with_auth):
        """Test PUT campaign with insufficient permissions"""
        campaign_id = 3
        
        # Mock the permission check to return False - this should cause an early return
        # before any service methods are called
        with patch('app.api.v1.routes.campaigns.root.check_allocation_permission', return_value=False):
            response = client_with_auth.put(f"/api/v1/campaigns/{campaign_id}", json=MOCK_CAMPAIGN_UPDATE)
            
            # The route should return 404 with "Allocation is incorrect" message
            assert response.status_code == 404
            response_json = response.json()
            assert "detail" in response_json
            assert response_json["detail"] == "Allocation is incorrect"



    def test_put_campaign_not_found(self, client_with_auth):
        """Test PUT campaign when campaign doesn't exist"""
        campaign_id = 999
        
        with patch('app.api.dependencies.pytas.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.update_campaign') as mock_update:
            
            mock_update.return_value = None
            
            response = client_with_auth.put(f"/api/v1/campaigns/{campaign_id}", json=MOCK_CAMPAIGN_UPDATE)
            
            assert response.status_code == 404
            assert response.json()["detail"] == "Campaign not found"

    def test_put_campaign_unauthorized(self, client_no_auth):
        """Test PUT campaign without authentication"""
        campaign_id = 3
        
        response = client_no_auth.put(f"/api/v1/campaigns/{campaign_id}", json=MOCK_CAMPAIGN_UPDATE)
        
        assert response.status_code == 401

    @pytest.mark.parametrize("campaign_id,expected_status", [
        (3, 200),  # Valid campaign
        (999, 404),  # Non-existent campaign
    ])
    def test_put_campaign_various_ids(self, client_with_auth, campaign_id, expected_status):
        """Test PUT campaign with various campaign IDs"""
        with patch('app.api.dependencies.pytas.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.update_campaign') as mock_update:
            
            if expected_status == 200:
                mock_update.return_value = CampaignCreateResponse(id=campaign_id)
            else:
                mock_update.return_value = None
            
            response = client_with_auth.put(f"/api/v1/campaigns/{campaign_id}", json=MOCK_CAMPAIGN_UPDATE)
            assert response.status_code == expected_status

    def test_put_campaign_invalid_data(self, client_with_auth):
        """Test PUT campaign with invalid data"""
        campaign_id = 3
        invalid_data = {
            "contact_email": "invalid-email"  # Invalid email format
        }
        
        with patch('app.api.dependencies.pytas.check_allocation_permission', return_value=True):
            response = client_with_auth.put(f"/api/v1/campaigns/{campaign_id}", json=invalid_data)
            
            assert response.status_code == 422  # Validation error

    def test_put_campaign_service_called_with_correct_params(self, client_with_auth):
        """Test that the service is called with correct parameters"""
        campaign_id = 3
        
        with patch('app.api.dependencies.pytas.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.update_campaign') as mock_update:
            
            mock_update.return_value = CampaignCreateResponse(id=campaign_id)
            
            response = client_with_auth.put(f"/api/v1/campaigns/{campaign_id}", json=MOCK_CAMPAIGN_UPDATE)
            
            assert response.status_code == 200
            # Verify the service was called with the correct campaign_id
            args, kwargs = mock_update.call_args
            assert args[0] == campaign_id  # First argument should be campaign_id

    def test_put_campaign_permission_check_called_correctly(self, client_with_auth):
        """Test that permission check is called with correct parameters"""
        campaign_id = 3
        mock_campaign = Mock()
        mock_campaign.campaignid = campaign_id
        
        # Create a spy function that tracks calls but still returns True
        permission_calls = []
        
        def permission_spy(user, campaign_id_param):
            permission_calls.append((user, campaign_id_param))
            return True
        
        with patch('app.api.v1.routes.campaigns.root.check_allocation_permission', side_effect=permission_spy), \
             patch('app.db.repositories.campaign_repository.CampaignRepository.update_campaign', return_value=mock_campaign):
            
            response = client_with_auth.put(f"/api/v1/campaigns/{campaign_id}", json=MOCK_CAMPAIGN_UPDATE)
            
            assert response.status_code == 200
            # Verify permission check was called once with correct parameters
            assert len(permission_calls) == 1
            called_user, called_campaign_id = permission_calls[0]
            assert called_user.username == MOCK_USER.username
            assert called_campaign_id == campaign_id


class TestCampaignPatchRoute:
    """Tests for PATCH /campaigns/{campaign_id}"""
    
    def test_patch_campaign_success(self, client_with_auth):
        """Test successful partial campaign update via PATCH"""
        campaign_id = 3
        
        with patch('app.api.dependencies.pytas.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.partial_update_campaign') as mock_partial_update:
            
            mock_partial_update.return_value = CampaignCreateResponse(id=campaign_id)
            
            response = client_with_auth.patch(f"/api/v1/campaigns/{campaign_id}", json=MOCK_PARTIAL_UPDATE)
            
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["id"] == campaign_id
            mock_partial_update.assert_called_once()

    def test_patch_campaign_permission_denied(self, client_with_auth):
        """Test PATCH campaign with insufficient permissions"""
        campaign_id = 3
        
        # Mock the permission check to return False - this should cause an early return
        # before any service methods are called
        with patch('app.api.v1.routes.campaigns.root.check_allocation_permission', return_value=False):
            response = client_with_auth.patch(f"/api/v1/campaigns/{campaign_id}", json=MOCK_PARTIAL_UPDATE)
            
            # The route should return 404 with "Allocation is incorrect" message
            assert response.status_code == 404
            response_json = response.json()
            assert "detail" in response_json
            assert response_json["detail"] == "Allocation is incorrect"

    def test_patch_campaign_not_found(self, client_with_auth):
        """Test PATCH campaign when campaign doesn't exist"""
        campaign_id = 999
        
        with patch('app.api.dependencies.pytas.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.partial_update_campaign') as mock_partial_update:
            
            mock_partial_update.return_value = None
            
            response = client_with_auth.patch(f"/api/v1/campaigns/{campaign_id}", json=MOCK_PARTIAL_UPDATE)
            
            assert response.status_code == 404
            assert response.json()["detail"] == "Campaign not found"

    def test_patch_campaign_unauthorized(self, client_no_auth):
        """Test PATCH campaign without authentication"""
        campaign_id = 3
        
        response = client_no_auth.patch(f"/api/v1/campaigns/{campaign_id}", json=MOCK_PARTIAL_UPDATE)
        
        assert response.status_code == 401

    def test_patch_campaign_single_field(self, client_with_auth):
        """Test PATCH campaign updating only one field"""
        campaign_id = 3
        single_field_update = {"name": "New Campaign Name Only"}
        
        with patch('app.api.dependencies.pytas.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.partial_update_campaign') as mock_partial_update:
            
            mock_partial_update.return_value = CampaignCreateResponse(id=campaign_id)
            
            response = client_with_auth.patch(f"/api/v1/campaigns/{campaign_id}", json=single_field_update)
            
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["id"] == campaign_id
            mock_partial_update.assert_called_once()

    def test_patch_campaign_empty_body(self, client_with_auth):
        """Test PATCH campaign with empty request body"""
        campaign_id = 3
        empty_update = {}
        
        with patch('app.api.dependencies.pytas.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.partial_update_campaign') as mock_partial_update:
            
            mock_partial_update.return_value = CampaignCreateResponse(id=campaign_id)
            
            response = client_with_auth.patch(f"/api/v1/campaigns/{campaign_id}", json=empty_update)
            
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["id"] == campaign_id
            mock_partial_update.assert_called_once()

    @pytest.mark.parametrize("campaign_id,expected_status", [
        (3, 200),  # Valid campaign
        (999, 404),  # Non-existent campaign
    ])
    def test_patch_campaign_various_ids(self, client_with_auth, campaign_id, expected_status):
        """Test PATCH campaign with various campaign IDs"""
        with patch('app.api.dependencies.pytas.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.partial_update_campaign') as mock_partial_update:
            
            if expected_status == 200:
                mock_partial_update.return_value = CampaignCreateResponse(id=campaign_id)
            else:
                mock_partial_update.return_value = None
            
            response = client_with_auth.patch(f"/api/v1/campaigns/{campaign_id}", json=MOCK_PARTIAL_UPDATE)
            assert response.status_code == expected_status

    def test_patch_campaign_service_called_with_correct_params(self, client_with_auth):
        """Test that the PATCH service is called with correct parameters"""
        campaign_id = 3
        
        with patch('app.api.dependencies.pytas.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.partial_update_campaign') as mock_partial_update:
            
            mock_partial_update.return_value = CampaignCreateResponse(id=campaign_id)
            
            response = client_with_auth.patch(f"/api/v1/campaigns/{campaign_id}", json=MOCK_PARTIAL_UPDATE)
            
            assert response.status_code == 200
            # Verify the service was called with the correct campaign_id
            args, kwargs = mock_partial_update.call_args
            assert args[0] == campaign_id  # First argument should be campaign_id

    def test_patch_campaign_permission_check_called_correctly(self, client_with_auth):
        """Test that permission check is called with correct parameters"""
        campaign_id = 3
        mock_campaign = Mock()
        mock_campaign.campaignid = campaign_id
        
        # Create a spy function that tracks calls but still returns True
        permission_calls = []
        
        def permission_spy(user, campaign_id_param):
            permission_calls.append((user, campaign_id_param))
            return True
        
        with patch('app.api.v1.routes.campaigns.root.check_allocation_permission', side_effect=permission_spy), \
             patch('app.db.repositories.campaign_repository.CampaignRepository.update_campaign', return_value=mock_campaign):
            
            response = client_with_auth.patch(f"/api/v1/campaigns/{campaign_id}", json=MOCK_PARTIAL_UPDATE)
            
            assert response.status_code == 200
            # Verify permission check was called once with correct parameters
            assert len(permission_calls) == 1
            called_user, called_campaign_id = permission_calls[0]
            assert called_user.username == MOCK_USER.username
            assert called_campaign_id == campaign_id


class TestCampaignUpdateIntegration:
    """Integration tests for campaign updates"""

    def test_put_vs_patch_behavior(self, client_with_auth):
        """Test that PUT and PATCH both work but call different service methods"""
        campaign_id = 3
        
        # Test PUT works
        with patch('app.api.dependencies.pytas.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.update_campaign') as mock_update:
            
            mock_update.return_value = CampaignCreateResponse(id=campaign_id)
            
            put_response = client_with_auth.put(f"/api/v1/campaigns/{campaign_id}", json=MOCK_CAMPAIGN_UPDATE)
            assert put_response.status_code == 200
            mock_update.assert_called_once()
        
        # Test PATCH works
        with patch('app.api.dependencies.pytas.check_allocation_permission', return_value=True), \
             patch('app.services.campaign_service.CampaignService.partial_update_campaign') as mock_partial_update:
            
            mock_partial_update.return_value = CampaignCreateResponse(id=campaign_id)
            
            patch_response = client_with_auth.patch(f"/api/v1/campaigns/{campaign_id}", json=MOCK_PARTIAL_UPDATE)
            assert patch_response.status_code == 200
            mock_partial_update.assert_called_once()

    @pytest.mark.parametrize("method,data,expected_status,service_method", [
        ("PUT", MOCK_CAMPAIGN_UPDATE, 200, "update_campaign"),
        ("PATCH", MOCK_PARTIAL_UPDATE, 200, "partial_update_campaign"),
    ])
    def test_different_http_methods(self, client_with_auth, method, data, expected_status, service_method):
        """Test different HTTP methods on campaign endpoint"""
        campaign_id = 3
        
        with patch(f'app.services.campaign_service.CampaignService.{service_method}') as mock_service:
            mock_service.return_value = CampaignCreateResponse(id=campaign_id)
            
            response = client_with_auth.request(method, f"/api/v1/campaigns/{campaign_id}", json=data)
            
            assert response.status_code == expected_status
            response_data = response.json()
            assert response_data["id"] == campaign_id
            mock_service.assert_called_once()
            args, kwargs = mock_service.call_args
            assert args[0] == campaign_id  # First argument should be campaign_id
            # The second parameter should be the CampaignsIn object
            assert hasattr(args[1], 'name')  # Should have campaign attributes

    def test_put_campaign_full_workflow(self, client_with_auth):
        """Test complete PUT workflow"""
        campaign_id = 3
        
        with patch('app.services.campaign_service.CampaignService.update_campaign') as mock_update:
            mock_update.return_value = CampaignCreateResponse(id=campaign_id)
            
            # Test the full request/response cycle
            response = client_with_auth.put(f"/api/v1/campaigns/{campaign_id}", json=MOCK_CAMPAIGN_UPDATE)
            
            # Verify response
            assert response.status_code == 200
            response_data = response.json()
            assert "id" in response_data
            assert response_data["id"] == campaign_id
            
            # Verify service was called correctly
            mock_update.assert_called_once()
            call_args = mock_update.call_args
            assert call_args[0][0] == campaign_id  # campaign_id parameter
            # The second parameter should be the CampaignsIn object
            assert hasattr(call_args[0][1], 'name')  # Should have campaign attributes