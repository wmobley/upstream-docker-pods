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
