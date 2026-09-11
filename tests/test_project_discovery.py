from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.project_discovery import discover_project_instances


def test_project_discovery_does_not_send_tenant_obo_header() -> None:
    settings = SimpleNamespace(
        TAPIS_SERVICE_USERNAME="tasclient_dsso",
        TAPIS_SERVICE_PASSWORD="service-password",
        TAS_USER=None,
        TAS_SECRET=None,
        TAPIS_BASE_URL="https://portals.tapis.io",
        TAPIS_TENANT_ID="portals",
        TAPIS_PODS_BASE_URL="https://portals.tapis.io",
    )
    auth_outcome = SimpleNamespace(tokens={"access_token": "service-token"})

    pods_response = Mock(status_code=200, headers={"content-type": "application/json"})
    pods_response.json.return_value = {
        "result": [
            {
                "pod_id": "fluxapi",
                "description": "[upstream] Flux",
                "networking": {"default": {"url": "fluxapi.pods.portals.tapis.io"}},
            }
        ]
    }
    role_response = Mock(status_code=200, headers={"content-type": "application/json"})
    role_response.json.return_value = {"role": "READ"}

    with (
        patch("app.services.project_discovery.get_settings", return_value=settings),
        patch("app.services.project_discovery.TapisAuthClient") as auth_client,
        patch("app.services.project_discovery.requests.get", side_effect=[pods_response, role_response]) as get,
    ):
        auth_client.return_value.authenticate.return_value = auth_outcome

        instances = discover_project_instances("user-token")

    assert instances[0]["stackId"] == "flux"
    pods_request_headers = get.call_args_list[0].kwargs["headers"]
    assert pods_request_headers == {
        "X-Tapis-Token": "service-token",
        "Accept": "application/json",
    }
    assert "X-Tapis-Tenant" not in pods_request_headers
