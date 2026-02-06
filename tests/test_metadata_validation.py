import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session

from app.main import app
from app.api.dependencies.auth import get_current_user, get_edit_user
from app.api.v1.schemas.user import User
from app.db.session import get_db


MOCK_USER = User(
    id=1,
    username="testuser",
    email="test@example.com",
    is_active=True,
    role="ADMIN",
)


def override_get_user():
    return MOCK_USER


def override_get_db():
    return Mock(spec=Session)


@pytest.fixture
def client_with_auth():
    app.dependency_overrides[get_current_user] = override_get_user
    app.dependency_overrides[get_edit_user] = override_get_user
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_create_campaign_rejects_unknown_metadata(client_with_auth):
    with patch("app.api.v1.routes.campaigns.root.MetadataSchemaRepository.list_schema", return_value=[]):
        response = client_with_auth.post(
            "/api/v1/campaigns",
            json={
                "name": "Test Campaign",
                "contact_name": "Jane",
                "contact_email": "jane@example.com",
                "allocation": "TEST-123",
                "start_date": "2024-01-01T00:00:00",
                "end_date": "2024-02-01T00:00:00",
                "metadata": {"unknown_key": "value"},
            },
        )
        assert response.status_code == 422
        data = response.json()
        assert "errors" in data.get("detail", {})
