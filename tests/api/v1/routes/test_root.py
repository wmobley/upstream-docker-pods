import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
import jwt
from app.main import app
from app.core.config import Settings
from app.api.dependencies.auth import AuthResult

client = TestClient(app)

# Test data
TEST_USERNAME = "test_user"
TEST_PASSWORD = "test_password"
TEST_TOKEN = "test.jwt.token"
TEST_JWT_SECRET = "test_secret"

@pytest.fixture
def mock_settings():
    with patch("app.core.config.get_settings") as mock:
        settings = Settings(
            JWT_SECRET=TEST_JWT_SECRET,
            TAS_USER=TEST_USERNAME,
            TAS_SECRET=TEST_PASSWORD,
            TAS_URL='http://localhost:5432',
            TAPIS_BASE_URL="https://tacc.tapis.io",
            TAPIS_TENANT_ID="tacc",
            TAPIS_ENFORCE_AUTH_IN_DEV=True,
            ALG="HS256",
            ENV="test",
            ENVIRONMENT="test",
            # Add any missing required settings here
            POSTGRES_PASSWORD="test",  # Add this if required
            DATABASE_URL="test"        # Add this if required
        )
        mock.return_value = settings
        yield mock

@pytest.fixture
def mock_authenticate_user():
    with patch("app.api.v1.routes.root.authenticate_user") as mock:
        mock.return_value = AuthResult(success=True, tapis_tokens={"access_token": "tapis-token"})
        yield mock


@pytest.fixture
def mock_resolve_user_role():
    with patch("app.api.v1.routes.root.resolve_user_role") as mock:
        mock.return_value = "USER"
        yield mock

def test_login_success(mock_settings, mock_authenticate_user, mock_resolve_user_role):
    response = client.post(
        "/api/v1/token",
        data={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert body["tapis_access_token"] == "tapis-token"
    assert body["role"] == "USER"

    # Verify the token is valid
    token = body["access_token"]
    decoded = jwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])
    assert decoded["username"] == TEST_USERNAME
    assert decoded["role"] == "USER"
    mock_resolve_user_role.assert_called_once_with(TEST_USERNAME, "tapis-token")

def test_login_failure(mock_settings):
    with patch("app.api.v1.routes.root.authenticate_user") as mock:
        mock.return_value = AuthResult(success=False)
        response = client.post(
            "/api/v1/token",
            data={"username": TEST_USERNAME, "password": "wrong_password"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Incorrect username or password"

def test_login_missing_credentials():
    response = client.post("/api/v1/token", data={})
    assert response.status_code == 422  # FastAPI validation error


def test_login_failure_with_detail(mock_settings):
    with patch("app.api.v1.routes.root.authenticate_user") as mock:
        mock.return_value = AuthResult(success=False, error="Tapis said nope")
        response = client.post(
            "/api/v1/token",
            data={"username": TEST_USERNAME, "password": "wrong_password"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Tapis said nope"
