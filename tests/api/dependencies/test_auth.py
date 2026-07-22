import jwt
import pytest
from app.api.dependencies import auth
from app.tapis.client import TapisTokenVerifier


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


def test_elevate_role_for_tas_allocation_no_op_when_not_primary(monkeypatch):
    monkeypatch.setattr(auth.settings, "IS_PRIMARY_INSTANCE", False)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("user_has_allocation must not be called when not primary")

    monkeypatch.setattr(auth, "user_has_allocation", fail_if_called)

    assert auth.elevate_role_for_tas_allocation("alice", "READ") == "READ"


def test_elevate_role_for_tas_allocation_never_downgrades(monkeypatch):
    monkeypatch.setattr(auth.settings, "IS_PRIMARY_INSTANCE", True)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("user_has_allocation must not be called for an already-elevated role")

    monkeypatch.setattr(auth, "user_has_allocation", fail_if_called)

    assert auth.elevate_role_for_tas_allocation("alice", "ADMIN") == "ADMIN"
    assert auth.elevate_role_for_tas_allocation("alice", "APPROVEDADMIN") == "APPROVEDADMIN"
    assert auth.elevate_role_for_tas_allocation("alice", "USER") == "USER"


def _make_test_session_local(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.models.user_role import UserRole as UserRoleModel

    engine = create_engine(f"sqlite:///{tmp_path}/test_elevate.db", connect_args={"check_same_thread": False})
    UserRoleModel.__table__.create(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def test_elevate_role_for_tas_allocation_elevates_on_match(monkeypatch, tmp_path):
    from app.db.repositories.user_role_repository import UserRoleRepository

    test_session_local = _make_test_session_local(tmp_path)

    monkeypatch.setattr(auth.settings, "IS_PRIMARY_INSTANCE", True)
    monkeypatch.setattr(auth.settings, "PRIMARY_ALLOCATION_CHARGE_CODE", "PT2050-DataX")
    monkeypatch.setattr(auth, "SessionLocal", test_session_local)
    monkeypatch.setattr(
        auth,
        "user_has_allocation",
        lambda username, charge_code: username == "alice" and charge_code == "PT2050-DataX",
    )

    assert auth.elevate_role_for_tas_allocation("alice", "READ") == "USER"

    with test_session_local() as db:
        record = UserRoleRepository(db).get_by_username("alice")
        assert record is not None
        assert record.role == "USER"


def test_elevate_role_for_tas_allocation_no_match_leaves_role_unchanged(monkeypatch, tmp_path):
    test_session_local = _make_test_session_local(tmp_path)

    monkeypatch.setattr(auth.settings, "IS_PRIMARY_INSTANCE", True)
    monkeypatch.setattr(auth, "SessionLocal", test_session_local)
    monkeypatch.setattr(auth, "user_has_allocation", lambda *_args, **_kwargs: False)

    assert auth.elevate_role_for_tas_allocation("alice", "READ") == "READ"


def test_elevate_role_for_tas_allocation_fails_safe_on_tas_error(monkeypatch):
    monkeypatch.setattr(auth.settings, "IS_PRIMARY_INSTANCE", True)

    def raise_error(*_args, **_kwargs):
        raise RuntimeError("TAS unavailable")

    monkeypatch.setattr(auth, "user_has_allocation", raise_error)

    assert auth.elevate_role_for_tas_allocation("alice", "READ") == "READ"


# ---------------------------------------------------------------------------
# TapisTokenVerifier tests
# ---------------------------------------------------------------------------

def _make_rsa_keypair():
    """Generate a throwaway RSA key pair for testing."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key, private_key.public_key()


def _pem(public_key) -> str:
    from cryptography.hazmat.primitives import serialization

    return public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def _sign_token(private_key, payload: dict) -> str:
    from cryptography.hazmat.primitives import serialization

    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    return jwt.encode(payload, pem, algorithm="RS256")


def test_tapis_token_verifier_valid_token(monkeypatch):
    private_key, public_key = _make_rsa_keypair()
    public_pem = _pem(public_key)

    verifier = TapisTokenVerifier(base_url="https://portals.tapis.io", tenant_id="portals")
    monkeypatch.setattr(verifier, "_fetch_public_key", lambda: public_pem)

    token = _sign_token(private_key, {"tapis/username": "alice", "sub": "alice@portals"})
    claims = verifier.verify(token)
    assert claims["tapis/username"] == "alice"


def test_tapis_token_verifier_invalid_signature(monkeypatch):
    _, public_key = _make_rsa_keypair()
    other_private_key, _ = _make_rsa_keypair()
    public_pem = _pem(public_key)

    verifier = TapisTokenVerifier(base_url="https://portals.tapis.io", tenant_id="portals")
    monkeypatch.setattr(verifier, "_fetch_public_key", lambda: public_pem)

    token = _sign_token(other_private_key, {"tapis/username": "eve"})
    with pytest.raises(jwt.InvalidSignatureError):
        verifier.verify(token)


def test_tapis_token_verifier_caches_public_key(monkeypatch):
    private_key, public_key = _make_rsa_keypair()
    public_pem = _pem(public_key)
    fetch_calls = {"count": 0}

    verifier = TapisTokenVerifier(base_url="https://portals.tapis.io", tenant_id="portals")

    def fake_fetch():
        fetch_calls["count"] += 1
        return public_pem

    monkeypatch.setattr(verifier, "_fetch_public_key", fake_fetch)

    token = _sign_token(private_key, {"tapis/username": "alice"})
    verifier.verify(token)
    verifier.verify(token)
    assert fetch_calls["count"] == 1  # second call uses cache


def test_username_from_claims_tapis_field():
    assert TapisTokenVerifier.username_from_claims({"tapis/username": "alice"}) == "alice"


def test_username_from_claims_sub_at_tenant():
    assert TapisTokenVerifier.username_from_claims({"sub": "alice@portals"}) == "alice"


def test_username_from_claims_sub_plain():
    assert TapisTokenVerifier.username_from_claims({"sub": "alice"}) == "alice"


@pytest.mark.asyncio
async def test_get_current_user_dev_bypass_when_not_enforced(monkeypatch):
    monkeypatch.setattr(auth.settings, "ENV", "dev")
    monkeypatch.setattr(auth.settings, "TAPIS_ENFORCE_AUTH_IN_DEV", False)

    user = await auth.get_current_user(token=None)
    assert user.username == "test"


@pytest.mark.asyncio
async def test_get_current_user_dev_bypass_disabled_when_enforced(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(auth.settings, "ENV", "dev")
    monkeypatch.setattr(auth.settings, "TAPIS_ENFORCE_AUTH_IN_DEV", True)

    with pytest.raises(HTTPException) as exc_info:
        await auth.get_current_user(token=None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_accepts_tapis_jwt(monkeypatch):
    private_key, public_key = _make_rsa_keypair()
    public_pem = _pem(public_key)

    monkeypatch.setattr(auth.settings, "ENV", "prod")

    verifier = TapisTokenVerifier(base_url="https://portals.tapis.io", tenant_id="portals")
    monkeypatch.setattr(verifier, "_fetch_public_key", lambda: public_pem)
    monkeypatch.setattr(auth, "tapis_token_verifier", verifier)

    token = _sign_token(private_key, {"tapis/username": "alice", "sub": "alice@portals"})
    user = await auth.get_current_user(token=token)
    assert user.username == "alice"


@pytest.mark.asyncio
async def test_get_current_user_rejects_bad_tapis_jwt(monkeypatch):
    from fastapi import HTTPException

    _, public_key = _make_rsa_keypair()
    other_private_key, _ = _make_rsa_keypair()
    public_pem = _pem(public_key)

    monkeypatch.setattr(auth.settings, "ENV", "prod")

    verifier = TapisTokenVerifier(base_url="https://portals.tapis.io", tenant_id="portals")
    monkeypatch.setattr(verifier, "_fetch_public_key", lambda: public_pem)
    monkeypatch.setattr(auth, "tapis_token_verifier", verifier)

    token = _sign_token(other_private_key, {"tapis/username": "eve"})
    with pytest.raises(HTTPException) as exc_info:
        await auth.get_current_user(token=token)
    assert exc_info.value.status_code == 401
