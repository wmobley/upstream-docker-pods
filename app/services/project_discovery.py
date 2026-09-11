from __future__ import annotations

import logging
from typing import Any, cast

import requests

from app.core.config import get_settings
from app.tapis.client import TapisAuthClient

logger = logging.getLogger(__name__)


def _api_url(pod: dict[str, Any], pods_base_url: str) -> str:
    networking = pod.get("networking") or {}
    entry = next(iter(networking.values()), {}) if isinstance(networking, dict) else {}
    url = entry.get("url") if isinstance(entry, dict) else None
    if url:
        return f"https://{url}".rstrip("/")
    pod_id = str(pod.get("pod_id", ""))
    host = pods_base_url.replace("https://", "").replace("http://", "").rstrip("/")
    return f"https://{pod_id}.pods.{host}"


def discover_project_instances(user_token: str) -> list[dict[str, str]]:
    """Discover candidate APIs with service credentials, then authorize the caller.

    The service account is used only for the catalog/list operation. The caller's
    token is forwarded to each project API, so ``/user-roles/me`` evaluates the
    actual end user rather than the service account.
    """
    settings = get_settings()
    if not settings.TAPIS_SERVICE_USERNAME or not settings.TAPIS_SERVICE_PASSWORD:
        raise RuntimeError("TAPIS_SERVICE_USERNAME and TAPIS_SERVICE_PASSWORD are required")

    auth = TapisAuthClient(settings.TAPIS_BASE_URL, settings.TAPIS_TENANT_ID)
    outcome = auth.authenticate(settings.TAPIS_SERVICE_USERNAME, settings.TAPIS_SERVICE_PASSWORD)
    service_token = (outcome.tokens or {}).get("access_token")
    if not service_token:
        raise RuntimeError("Unable to obtain Tapis service token")

    configured_pods_base = settings.TAPIS_PODS_BASE_URL or ""
    if configured_pods_base.strip():
        pods_base = configured_pods_base.rstrip("/")
    else:
        tapis_host = settings.TAPIS_BASE_URL.replace("https://", "").replace("http://", "").rstrip("/")
        pods_base = f"https://pods.{tapis_host}"
    response = requests.get(
        f"{pods_base}/v3/pods",
        headers={"X-Tapis-Token": service_token, "Accept": "application/json"},
        timeout=20,
    )
    response.raise_for_status()
    payload = cast(dict[str, Any], response.json())
    pods = payload.get("result", []) if isinstance(payload, dict) else []

    instances: list[dict[str, str]] = []
    for pod in pods if isinstance(pods, list) else []:
        if not isinstance(pod, dict):
            continue
        pod_id = str(pod.get("pod_id", ""))
        description = str(pod.get("description", ""))
        if not pod_id.endswith("api") or not description.startswith("[upstream]"):
            continue
        api_url = _api_url(pod, pods_base)
        try:
            role_response = requests.get(
                f"{api_url}/api/v1/user-roles/me",
                headers={"Authorization": f"Bearer {user_token}", "Accept": "application/json"},
                timeout=10,
            )
            if role_response.status_code in (401, 403):
                continue
            role_response.raise_for_status()
            role = str((role_response.json() or {}).get("role", "")).upper()
            if role not in {"READ", "USER", "APPROVEDADMIN", "ADMIN"}:
                continue
            stack_id = pod_id[:-3]
            instances.append({
                "stackId": stack_id,
                "displayName": description.removeprefix("[upstream]").strip() or stack_id,
                "apiUrl": api_url,
                "permission": "ADMIN" if role in {"ADMIN", "APPROVEDADMIN"} else role,
            })
        except requests.RequestException as exc:
            logger.warning("Project role lookup failed for %s: %s", pod_id, exc)
    return instances
