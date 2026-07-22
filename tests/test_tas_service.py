from app.pytas.http import TASClient
from app.services import tas_service


def test_tas_client_defaults_from_settings(monkeypatch):
    import app.pytas.http as pytas_http

    class FakeSettings:
        TAS_URL = "https://tas.example"
        TAS_USER = "svc_user"
        TAS_SECRET = "svc_secret"

    monkeypatch.setattr(pytas_http, "get_settings", lambda: FakeSettings())

    client = TASClient()
    assert client.baseURL == "https://tas.example"
    assert client.credentials == {"username": "svc_user", "password": "svc_secret"}
    assert client.auth.username == "svc_user"
    assert client.auth.password == "svc_secret"


def test_tas_client_explicit_args_override_settings(monkeypatch):
    import app.pytas.http as pytas_http

    class FakeSettings:
        TAS_URL = "https://tas.example"
        TAS_USER = "svc_user"
        TAS_SECRET = "svc_secret"

    monkeypatch.setattr(pytas_http, "get_settings", lambda: FakeSettings())

    client = TASClient(baseURL="https://other.example", credentials={"username": "u", "password": "p"})
    assert client.baseURL == "https://other.example"
    assert client.credentials == {"username": "u", "password": "p"}


class FakeProject:
    def __init__(self, charge_code):
        self.chargeCode = charge_code


def test_user_has_allocation_matches_case_insensitively(monkeypatch):
    class FakeClient:
        def projects_for_user(self, username):
            assert username == "alice"
            return [FakeProject("PT1000-Other"), FakeProject("pt2050-datax")]

    monkeypatch.setattr(tas_service, "TASClient", lambda: FakeClient())

    assert tas_service.user_has_allocation("alice", "PT2050-DataX") is True


def test_user_has_allocation_no_match(monkeypatch):
    class FakeClient:
        def projects_for_user(self, username):
            return [FakeProject("PT1000-Other")]

    monkeypatch.setattr(tas_service, "TASClient", lambda: FakeClient())

    assert tas_service.user_has_allocation("alice", "PT2050-DataX") is False


def test_user_has_allocation_empty_inputs():
    assert tas_service.user_has_allocation("", "PT2050-DataX") is False
    assert tas_service.user_has_allocation("alice", "") is False
