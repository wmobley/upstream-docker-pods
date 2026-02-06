import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session

from app.main import app
from app.api.dependencies.auth import get_current_user, get_viewer_user, get_admin_user
from app.api.v1.schemas.user import User
from app.db.models.metadata_schema import MetadataSchema
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
    app.dependency_overrides[get_viewer_user] = override_get_user
    app.dependency_overrides[get_admin_user] = override_get_user
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_list_metadata_schema(client_with_auth):
    item = MetadataSchema(
        id=1,
        scope="campaign",
        key="project_name",
        label="Project Name",
        field_type="string",
        required=False,
        help_text=None,
        units=None,
        ckan_field=None,
        ckan_mode="extra",
        order_index=0,
        active=True,
        options=None,
    )
    with patch("app.api.v1.routes.metadata_schema.MetadataSchemaRepository.list_schema", return_value=[item]):
        response = client_with_auth.get("/api/v1/metadata-schema")
        assert response.status_code == 200
        data = response.json()
        assert data["items"][0]["key"] == "project_name"


def test_create_metadata_schema(client_with_auth):
    item = MetadataSchema(
        id=2,
        scope="station",
        key="instrument_type",
        label="Instrument Type",
        field_type="string",
        required=False,
        help_text=None,
        units=None,
        ckan_field=None,
        ckan_mode="extra",
        order_index=0,
        active=True,
        options=None,
    )
    with patch("app.api.v1.routes.metadata_schema.MetadataSchemaRepository.create", return_value=item):
        response = client_with_auth.post(
            "/api/v1/metadata-schema",
            json={
                "scope": "station",
                "key": "instrument_type",
                "label": "Instrument Type",
                "field_type": "string",
                "required": False,
                "ckan_mode": "extra",
            },
        )
        assert response.status_code == 200
        assert response.json()["id"] == 2
