import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.api.dependencies import auth as auth_module
from app.api.dependencies.auth import get_admin_user, get_current_user
from app.api.v1.schemas.user import User
from app.db.models.user_role import UserRole as UserRoleModel
from app.db.session import get_db


SQLALCHEMY_DATABASE_URL = "sqlite:///./test_user_roles.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():  # type: ignore[no-untyped-def]
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_database():
    UserRoleModel.__table__.drop(bind=engine, checkfirst=True)
    UserRoleModel.__table__.create(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_admin_user] = lambda: User(username="admin", role="ADMIN")
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_upsert_user_role_creates_entry(client: TestClient):
    response = client.put("/api/v1/user-roles/example", json={"role": "USER"})
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "example"
    assert data["role"] == "USER"

    listing = client.get("/api/v1/user-roles")
    assert listing.status_code == 200
    roles = listing.json()
    assert any(role["username"] == "example" and role["role"] == "USER" for role in roles)


def test_upsert_user_role_updates_existing(client: TestClient):
    client.put("/api/v1/user-roles/example", json={"role": "READ"})
    response = client.put("/api/v1/user-roles/example", json={"role": "ADMIN"})
    assert response.status_code == 200
    assert response.json()["role"] == "ADMIN"


def test_delete_user_role(client: TestClient):
    client.put("/api/v1/user-roles/example", json={"role": "USER"})
    response = client.delete("/api/v1/user-roles/example")
    assert response.status_code == 204

    missing = client.delete("/api/v1/user-roles/example")
    assert missing.status_code == 404


def test_get_my_role_returns_caller_role(client: TestClient):
    app.dependency_overrides[get_current_user] = lambda: User(username="alice", role="USER")
    try:
        response = client.get("/api/v1/user-roles/me")
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "alice"
    assert data["role"] == "USER"


def test_get_my_role_does_not_require_admin(client: TestClient):
    # A caller with role NONE (no admin) must still be able to look up their
    # own role — this endpoint has no admin gate, unlike GET /user-roles.
    app.dependency_overrides[get_current_user] = lambda: User(username="bob", role="NONE")
    try:
        response = client.get("/api/v1/user-roles/me")
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 200
    assert response.json()["role"] == "NONE"


def test_get_my_role_requires_authentication(client: TestClient, monkeypatch):
    # No get_current_user override here — the real dependency runs. This repo's
    # .env defaults to ENV=dev, which would otherwise hit get_current_user's
    # dev-mode bypass and return a fake user with no token at all — force
    # enforcement on so this test actually exercises the auth check.
    monkeypatch.setattr(auth_module.settings, "TAPIS_ENFORCE_AUTH_IN_DEV", True)
    response = client.get("/api/v1/user-roles/me")
    assert response.status_code == 401
