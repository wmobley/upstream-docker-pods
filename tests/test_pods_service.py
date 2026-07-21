from app.services.pods_service import PodsService


def test_create_pod_treats_already_exists_as_success():
    service = PodsService.__new__(PodsService)

    def fake_request(*, method, path, json=None, token=None):
        raise RuntimeError(
            '{"detail":"{\\"status\\":\\"error\\",\\"message\\":\\"Got IntegrityError - '
            'psycopg2.errors.UniqueViolation : Key (pod_id)=(snifferpostgres) already exists.\\"}"}'
        )

    service._request = fake_request

    result = service.create_pod({"pod_id": "snifferpostgres"})

    assert result == {"status": "exists", "pod_id": "snifferpostgres"}


def test_create_pod_reraises_unrelated_errors():
    service = PodsService.__new__(PodsService)

    def fake_request(*, method, path, json=None, token=None):
        raise RuntimeError("Some other unrelated failure")

    service._request = fake_request

    try:
        service.create_pod({"pod_id": "snifferpostgres"})
        assert False, "expected RuntimeError to propagate"
    except RuntimeError as exc:
        assert "unrelated failure" in str(exc)


def test_build_bundle_grants_admin_permissions(monkeypatch):
    service = PodsService.__new__(PodsService)
    service.settings = type(
        "Settings",
        (),
        {
            "TAPIS_PODS_BASE_URL": "https://portals.tapis.io",
            "TAPIS_BASE_URL": "https://portals.tapis.io",
            "TAPIS_TENANT_ID": "portals",
            "TAS_USER": "user",
            "TAS_SECRET": "secret",
            "JWT_SECRET": "jwt",
            "ALG": "HS256",
            "TAS_URL": "https://tas.example",
            "ENVIRONMENT": "dev",
            "ENV": "dev",
            "CKAN_URL": None,
            "CKAN_TIMEOUT": 30,
            "CKAN_ORGANIZATION": None,
            "CKAN_ADMIN_USERNAME": "dso_test",
            "CKAN_ADMIN_API_KEY": "",
            "UI_BASE_URL": "https://ui.example",
            "API_BASE_URL": "https://api.example",
            "DEFAULT_ADMIN_USERS": ["wmobley", "tasclient_dsso"],
        },
    )()

    calls: list[tuple[str, str, str | dict[str, object]]] = []

    def fake_create_volume(*, volume_id: str, description: str):
        calls.append(("create_volume", volume_id, description))
        return {"volume_id": volume_id}

    def fake_create_pod(payload):
        pod_id = payload["pod_id"]
        calls.append(("create_pod", pod_id, payload))
        return {"pod_id": pod_id}

    def fake_set_volume_permission(*, volume_id: str, user: str, level: str = "ADMIN"):
        calls.append(("set_volume_permission", volume_id, f"{user}:{level}"))
        return {"volume_id": volume_id, "user": user, "level": level}

    def fake_set_pod_permission(*, pod_id: str, user: str, level: str = "ADMIN"):
        calls.append(("set_pod_permission", pod_id, f"{user}:{level}"))
        return {"pod_id": pod_id, "user": user, "level": level}

    def fake_set_stack_permission(*, stack_id: str, user: str, level: str = "ADMIN"):
        calls.append(("set_stack_permission", stack_id, f"{user}:{level}"))
        return {"stack_id": stack_id, "user": user, "level": level}

    service.create_stack = lambda *, stack_id, description="": {"stack_id": stack_id}
    service.create_volume = fake_create_volume
    service.create_pod = fake_create_pod
    service.set_volume_permission = fake_set_volume_permission
    service.set_pod_permission = fake_set_pod_permission
    service.set_stack_permission = fake_set_stack_permission
    service._bootstrap_pod_cors = lambda *, pod_id, cors_config: {"status": "configured"}

    created = service.build_bundle(base="sniffer", pg_user="pguser", pg_password="pgpass")

    assert created["stack"] == {"stack_id": "sniffer"}
    assert created["volume"] == {"volume_id": "sniffervolume"}
    assert created["postgres"] == {"pod_id": "snifferpostgres"}
    assert created["api"] == {"pod_id": "snifferapi"}
    assert "ui" not in created
    assert created["permissions"]["stack"]["tasclient_dsso"]["level"] == "ADMIN"
    assert created["permissions"]["volume"]["tasclient_dsso"]["level"] == "ADMIN"
    assert created["permissions"]["pods"]["snifferpostgres"]["tasclient_dsso"]["level"] == "ADMIN"
    assert created["permissions"]["pods"]["snifferapi"]["tasclient_dsso"]["level"] == "ADMIN"
    assert "sniffer" not in created["permissions"]["pods"]

    pod_payloads = {
        pod_id: payload
        for action, pod_id, payload in calls
        if action == "create_pod" and isinstance(payload, dict)
    }
    # UI pod must not be created
    assert "sniffer" not in pod_payloads
    assert pod_payloads["snifferpostgres"]["networking"]["default"]["url"] == (
        "snifferpostgres.pods.portals.tapis.io"
    )
    assert pod_payloads["snifferapi"]["environment_variables"]["DATABASE_URL"] == (
        "postgresql+psycopg://pguser:pgpass@snifferpostgres.pods.portals.tapis.io:443/pguser"
    )
    assert pod_payloads["snifferapi"]["environment_variables"]["API_BASE_URL"] == (
        "https://snifferapi.pods.portals.tapis.io"
    )
    # VITE_UPSTREAM_API_URL must be removed from api env vars
    assert "VITE_UPSTREAM_API_URL" not in pod_payloads["snifferapi"]["environment_variables"]
    # stack_id must be present in api payload
    assert pod_payloads["snifferapi"]["stack_id"] == "sniffer"
    # description defaults to '[upstream] <base>' when no display_name provided
    assert pod_payloads["snifferapi"]["description"] == "[upstream] sniffer"
    # CORS must NOT be in the create payload — Tapis gates cors_* writes behind
    # APPROVEDADMIN, which the creating user's own token never holds. CORS is
    # configured by a separate post-creation bootstrap step (see below).
    api_networking = pod_payloads["snifferapi"]["networking"]["default"]
    assert "cors_allow_origins" not in api_networking
    assert "cors_allow_methods" not in api_networking
    assert created["cors"] == {"status": "configured"}


def test_build_bundle_custom_description(monkeypatch):
    service = PodsService.__new__(PodsService)
    service.settings = type(
        "Settings",
        (),
        {
            "TAPIS_PODS_BASE_URL": "https://portals.tapis.io",
            "TAPIS_BASE_URL": "https://portals.tapis.io",
            "TAPIS_TENANT_ID": "portals",
            "TAS_USER": "user",
            "TAS_SECRET": "secret",
            "JWT_SECRET": "jwt",
            "ALG": "HS256",
            "TAS_URL": "https://tas.example",
            "ENVIRONMENT": "dev",
            "ENV": "dev",
            "CKAN_URL": None,
            "CKAN_TIMEOUT": 30,
            "CKAN_ORGANIZATION": None,
            "CKAN_ADMIN_USERNAME": "dso_test",
            "CKAN_ADMIN_API_KEY": "",
            "UI_BASE_URL": "https://ui.example",
            "API_BASE_URL": "https://api.example",
            "DEFAULT_ADMIN_USERS": [],
        },
    )()

    def fake_create_volume(*, volume_id: str, description: str):
        return {"volume_id": volume_id}

    captured: list[dict] = []

    def fake_create_pod(payload):
        captured.append(dict(payload))
        return {"pod_id": payload["pod_id"]}

    service.create_stack = lambda *, stack_id, description="": {"stack_id": stack_id}
    service.create_volume = fake_create_volume
    service.create_pod = fake_create_pod
    service.grant_default_admin_permissions = lambda **kw: {}
    service._bootstrap_pod_cors = lambda *, pod_id, cors_config: {"status": "configured"}

    service.build_bundle(
        base="myproject",
        pg_user="pguser",
        pg_password="pgpass",
        description="My Project API",
    )

    api_payload = next(p for p in captured if p["pod_id"] == "myprojectapi")
    assert api_payload["description"] == "[upstream] My Project API"


def test_bootstrap_pod_cors_success():
    service = PodsService.__new__(PodsService)
    service.settings = type(
        "Settings", (), {"TAPIS_SERVICE_USERNAME": "svc_account", "TAS_USER": "user"}
    )()
    service._fetch_service_token = lambda: "svc-token"

    calls: list[tuple[str, str, dict | None, str | None]] = []

    def fake_request(*, method, path, json=None, token=None):
        calls.append((method, path, json, token))
        return {"result": "ok"}

    service._request = fake_request

    result = service._bootstrap_pod_cors(
        pod_id="snifferapi",
        cors_config={
            "protocol": "http",
            "port": 8000,
            "url": "snifferapi.pods.portals.tapis.io",
            "cors_allow_origins": ["https://sniffer.pods.portals.tapis.io"],
        },
    )

    assert result == {"status": "configured"}
    assert calls[0] == (
        "POST",
        "/v3/pods/snifferapi/permissions",
        {"user": "svc_account", "level": "APPROVEDADMIN"},
        "svc-token",
    )
    method, path, json_body, token = calls[1]
    assert (method, path, token) == ("PUT", "/v3/pods/snifferapi", "svc-token")
    assert json_body["networking"]["default"]["cors_allow_origins"] == [
        "https://sniffer.pods.portals.tapis.io"
    ]


def test_bootstrap_pod_cors_grant_failure_does_not_raise():
    service = PodsService.__new__(PodsService)
    service.settings = type(
        "Settings", (), {"TAPIS_SERVICE_USERNAME": "svc_account", "TAS_USER": "user"}
    )()
    service._fetch_service_token = lambda: "svc-token"

    def fake_request(*, method, path, json=None, token=None):
        raise RuntimeError("No user has APPROVEDADMIN permission to configure CORS settings")

    service._request = fake_request

    result = service._bootstrap_pod_cors(pod_id="snifferapi", cors_config={"protocol": "http"})

    assert result["status"] == "pending_manual_approval"
    assert "APPROVEDADMIN" in result["error"]


def test_bootstrap_pod_cors_no_service_credentials():
    service = PodsService.__new__(PodsService)
    service.settings = type(
        "Settings",
        (),
        {
            "TAPIS_SERVICE_USERNAME": None,
            "TAPIS_SERVICE_PASSWORD": None,
            "TAS_USER": None,
            "TAS_SECRET": None,
        },
    )()

    result = service._bootstrap_pod_cors(pod_id="snifferapi", cors_config={"protocol": "http"})

    assert result["status"] == "pending_manual_approval"
    assert "not configured" in result["error"]
