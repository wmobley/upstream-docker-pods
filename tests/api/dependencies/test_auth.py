from app.api.dependencies import auth


def test_authenticate_user_dev_env_skips_credentials(monkeypatch):
    monkeypatch.setattr(auth.settings, "ENV", "dev")
    monkeypatch.setattr(auth.settings, "TAPIS_ENFORCE_AUTH_IN_DEV", False)
    result = auth.authenticate_user("", "")
    assert result.success is True
    assert result.tapis_tokens is None


def test_authenticate_user_dev_env_enforced(monkeypatch):
    monkeypatch.setattr(auth.settings, "ENV", "dev")
    monkeypatch.setattr(auth.settings, "TAPIS_ENFORCE_AUTH_IN_DEV", True)

    result = auth.authenticate_user("user", "pass")
    assert result.success is True
    assert result.tapis_tokens is None


def test_authenticate_user_non_dev_success(monkeypatch):
    monkeypatch.setattr(auth.settings, "ENV", "prod")

    result = auth.authenticate_user("user", "pass")
    assert result.success is True
    assert result.tapis_tokens is None


def test_authenticate_user_missing_credentials(monkeypatch):
    monkeypatch.setattr(auth.settings, "ENV", "prod")

    result = auth.authenticate_user("", "")
    assert result.success is False
    assert result.tapis_tokens is None
