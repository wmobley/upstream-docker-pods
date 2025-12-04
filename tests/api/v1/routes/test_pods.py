import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.dependencies.auth import get_edit_user
from app.api.v1.schemas.user import User


client = TestClient(app)


@pytest.fixture(autouse=True)
def override_edit_user():
    app.dependency_overrides[get_edit_user] = lambda: User(username="tester", role="USER")
    yield
    app.dependency_overrides.pop(get_edit_user, None)


def test_create_pod_bundle_invokes_service(monkeypatch):
    calls = {}

    class DummyService:
        def __init__(self, token_override=None):
            calls["init"] = calls.get("init", 0) + 1

        def build_bundle(self, *, base, pg_user, pg_password):
            calls["args"] = (base, pg_user, pg_password)
            return {"volume": "ok", "api": "ok", "ui": "ok"}

    monkeypatch.setattr("app.api.v1.routes.pods.PodsService", DummyService)

    response = client.post(
        "/api/v1/pods/bundle",
        json={"base": "sniffer", "pg_user": "pguser", "pg_password": "pgpass"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "requested"
    assert body["created"] == {"volume": "ok", "api": "ok", "ui": "ok"}
    assert calls["args"] == ("sniffer", "pguser", "pgpass")


def test_create_pod_bundle_validation_error(monkeypatch):
    class DummyService:
        def __init__(self, token_override=None):
            pass

        def build_bundle(self, *, base, pg_user, pg_password):  # pragma: no cover - mocked
            raise ValueError("bad base")

    monkeypatch.setattr("app.api.v1.routes.pods.PodsService", DummyService)

    response = client.post(
        "/api/v1/pods/bundle",
        json={"base": "", "pg_user": "pguser", "pg_password": "pgpass"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "bad base"
