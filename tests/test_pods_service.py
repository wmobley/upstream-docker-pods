from app.services.pods_service import PodsService


def test_build_bundle_grants_admin_permissions(monkeypatch):
    service = PodsService.__new__(PodsService)
    service.settings = type(
        "Settings",
        (),
        {
            "TAPIS_PODS_BASE_URL": "https://portals.tapis.io",
            "TAPIS_BASE_URL": "https://portals.tapis.io",
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

    service.create_volume = fake_create_volume
    service.create_pod = fake_create_pod
    service.set_volume_permission = fake_set_volume_permission
    service.set_pod_permission = fake_set_pod_permission

    created = service.build_bundle(base="sniffer", pg_user="pguser", pg_password="pgpass")

    assert created["volume"] == {"volume_id": "sniffervolume"}
    assert created["postgres"] == {"pod_id": "snifferpostgres"}
    assert created["api"] == {"pod_id": "snifferapi"}
    assert created["ui"] == {"pod_id": "sniffer"}
    assert created["permissions"]["volume"]["tasclient_dsso"]["level"] == "ADMIN"
    assert created["permissions"]["pods"]["snifferpostgres"]["tasclient_dsso"]["level"] == "ADMIN"
    assert created["permissions"]["pods"]["snifferapi"]["tasclient_dsso"]["level"] == "ADMIN"
    assert created["permissions"]["pods"]["sniffer"]["tasclient_dsso"]["level"] == "ADMIN"
