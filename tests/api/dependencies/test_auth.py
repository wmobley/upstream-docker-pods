from app.api.dependencies import auth


def test_authenticate_user_dev_env_skips_credentials(monkeypatch):
    monkeypatch.setattr(auth.settings, "ENV", "dev")
    monkeypatch.setattr(auth.settings, "TAPIS_ENFORCE_AUTH_IN_DEV", False)
    monkeypatch.setattr(auth, "tapis_auth_client", None)
    result = auth.authenticate_user("", "")
    assert result.success is True
    assert result.tapis_tokens is None


def test_authenticate_user_dev_env_attempts_tapis(monkeypatch):
    monkeypatch.setattr(auth.settings, "ENV", "dev")
    monkeypatch.setattr(auth.settings, "TAPIS_ENFORCE_AUTH_IN_DEV", False)

    class DummyOutcome:
        def __init__(self):
            self.tokens = {"access_token": "token123"}

    class DummyClient:
        def __init__(self):
            self.calls = 0

        def authenticate(self, username, password):
            self.calls += 1
            assert username == "user"
            assert password == "pass"
            return DummyOutcome()

    dummy = DummyClient()
    monkeypatch.setattr(auth, "tapis_auth_client", dummy)

    result = auth.authenticate_user("user", "pass")
    assert dummy.calls == 1
    assert result.success is True
    assert result.tapis_tokens == {"access_token": "token123"}


def test_authenticate_user_dev_env_bad_credentials_fail(monkeypatch):
    monkeypatch.setattr(auth.settings, "ENV", "dev")
    monkeypatch.setattr(auth.settings, "TAPIS_ENFORCE_AUTH_IN_DEV", False)

    class DummyOutcome:
        def __init__(self):
            self.tokens = None
            self.error = "invalid"

    class DummyClient:
        def authenticate(self, username, password):
            return DummyOutcome()

    monkeypatch.setattr(auth, "tapis_auth_client", DummyClient())

    result = auth.authenticate_user("user", "wrong")
    assert result.success is False
    assert result.error == "invalid"


def test_authenticate_user_dev_env_enforced(monkeypatch):
    monkeypatch.setattr(auth.settings, "ENV", "dev")
    monkeypatch.setattr(auth.settings, "TAPIS_ENFORCE_AUTH_IN_DEV", True)
    monkeypatch.setattr(auth, "tapis_auth_client", None)

    result = auth.authenticate_user("user", "pass")
    assert result.success is True
    assert result.tapis_tokens is None


def test_authenticate_user_non_dev_success(monkeypatch):
    monkeypatch.setattr(auth.settings, "ENV", "prod")
    monkeypatch.setattr(auth, "tapis_auth_client", None)

    result = auth.authenticate_user("user", "pass")
    assert result.success is True
    assert result.tapis_tokens is None


def test_authenticate_user_missing_credentials(monkeypatch):
    monkeypatch.setattr(auth.settings, "ENV", "prod")
    monkeypatch.setattr(auth, "tapis_auth_client", None)

    result = auth.authenticate_user("", "")
    assert result.success is False
    assert result.tapis_tokens is None


def test_authenticate_user_non_dev_tapis_failure(monkeypatch):
    monkeypatch.setattr(auth.settings, "ENV", "prod")

    class DummyOutcome:
        def __init__(self):
            self.tokens = None
            self.error = "bad creds"

    class DummyClient:
        def authenticate(self, username, password):
            return DummyOutcome()

    monkeypatch.setattr(auth, "tapis_auth_client", DummyClient())
    result = auth.authenticate_user("user", "pass")
    assert result.success is False
    assert result.error == "bad creds"


def test_ensure_ckan_membership_invokes_service(monkeypatch):
    monkeypatch.setattr(auth.settings, "CKAN_ORGANIZATION", "upstream")
    monkeypatch.setattr(auth.settings, "CKAN_ADMIN_API_KEY", "api-key-123")
    monkeypatch.setattr(auth.settings, "CKAN_ADMIN_USERNAME", "dso_test")

    captured: dict = {}

    class DummyService:
        def ensure_user_in_organization(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(auth, "get_ckan_service", lambda: DummyService())

    auth.ensure_ckan_membership("alice", "USER")
    assert captured == {
        "api_key": "api-key-123",
        "organization": "upstream",
        "username": "alice",
        "role": "admin",
        "requestor": "dso_test",
    }


def test_ensure_ckan_membership_skips_ineligible_role(monkeypatch):
    monkeypatch.setattr(auth.settings, "CKAN_ORGANIZATION", "upstream")
    monkeypatch.setattr(auth.settings, "CKAN_ADMIN_API_KEY", "api-key-123")
    calls = {"count": 0}

    class DummyService:
        def ensure_user_in_organization(self, **_kwargs):
            calls["count"] += 1

    monkeypatch.setattr(auth, "get_ckan_service", lambda: DummyService())

    auth.ensure_ckan_membership("alice", "READ")
    assert calls["count"] == 0
