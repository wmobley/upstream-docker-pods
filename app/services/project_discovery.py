from __future__ import annotations

import logging
from typing import Any, cast

import requests

from app.core.config import get_settings
from app.tapis.client import TapisAuthClient

logger = logging.getLogger(__name__)


def _api_url(pod: dict[str, Any], pods_base_url: str) -> str:
    networking = pod.get("networking") or {}
    entry: dict[str, Any] = next(iter(networking.values()), {}) if isinstance(networking, dict) else {}
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
    service_username = settings.TAPIS_SERVICE_USERNAME or settings.TAS_USER
    service_password = settings.TAPIS_SERVICE_PASSWORD or settings.TAS_SECRET
    logger.info(
        "project_discovery_started extra=%s",
        {
            "tenant": settings.TAPIS_TENANT_ID,
            "tapis_base_url": settings.TAPIS_BASE_URL,
            "pods_base_url_configured": bool(settings.TAPIS_PODS_BASE_URL),
            "service_username_configured": bool(service_username),
            "service_password_configured": bool(service_password),
        },
    )
    if not service_username or not service_password:
        logger.error("project_discovery_service_credentials_missing")
        raise RuntimeError("TAPIS_SERVICE_USERNAME and TAPIS_SERVICE_PASSWORD are required")

    auth = TapisAuthClient(settings.TAPIS_BASE_URL, settings.TAPIS_TENANT_ID)
    logger.info("project_discovery_service_auth_started extra=%s", {"username": service_username})
    try:
        outcome = auth.authenticate(service_username, service_password)
    except Exception as exc:
        logger.exception(
            "project_discovery_service_auth_failed extra=%s",
            {"error_type": type(exc).__name__},
        )
        raise
    service_token = (outcome.tokens or {}).get("access_token")
    if not service_token:
        logger.error("project_discovery_service_auth_missing_access_token")
        raise RuntimeError("Unable to obtain Tapis service token")

    configured_pods_base = settings.TAPIS_PODS_BASE_URL or ""
    if configured_pods_base.strip():
        pods_base = configured_pods_base.rstrip("/")
    else:
        tapis_host = settings.TAPIS_BASE_URL.replace("https://", "").replace("http://", "").rstrip("/")
        pods_base = f"https://pods.{tapis_host}"
    pods_url = f"{pods_base}/v3/pods"
    logger.info(
        "project_discovery_pods_request_started extra=%s",
        {"url": pods_url, "tenant": settings.TAPIS_TENANT_ID, "timeout_seconds": 20},
    )
    try:
        response = requests.get(
            pods_url,
            headers={
                "X-Tapis-Token": service_token,
                "X-Tapis-Tenant": settings.TAPIS_TENANT_ID,
                "Accept": "application/json",
            },
            timeout=20,
        )
    except Exception as exc:
        logger.exception(
            "project_discovery_pods_request_failed extra=%s",
            {"url": pods_url, "error_type": type(exc).__name__},
        )
        raise
    logger.info(
        "project_discovery_pods_response extra=%s",
        {
            "status_code": response.status_code,
            "service": "tapis-pods",
            "content_type": response.headers.get("content-type", ""),
        },
    )
    try:
        response.raise_for_status()
        payload = cast(dict[str, Any], response.json())
    except Exception as exc:
        logger.exception(
            "project_discovery_pods_response_invalid extra=%s",
            {"status_code": response.status_code, "error_type": type(exc).__name__},
        )
        raise
    pods = payload.get("result", []) if isinstance(payload, dict) else []
    logger.info(
        "project_discovery_pods_parsed extra=%s",
        {"pod_count": len(pods) if isinstance(pods, list) else None},
    )

    instances: list[dict[str, str]] = []
    candidate_count = 0
    for pod in pods if isinstance(pods, list) else []:
        if not isinstance(pod, dict):
            continue
        pod_id = str(pod.get("pod_id", ""))
        description = str(pod.get("description", ""))
        if not pod_id.endswith("api") or not description.startswith("[upstream]"):
            continue
        candidate_count += 1
        api_url = _api_url(pod, pods_base)
        logger.info(
            "project_discovery_role_lookup_started extra=%s",
            {"pod_id": pod_id, "api_url": api_url},
        )
        try:
            role_response = requests.get(
                f"{api_url}/api/v1/user-roles/me",
                headers={"Authorization": f"Bearer {user_token}", "Accept": "application/json"},
                timeout=10,
            )
            logger.info(
                "project_discovery_role_lookup_response extra=%s",
                {"pod_id": pod_id, "status_code": role_response.status_code},
            )
            if role_response.status_code in (401, 403):
                continue
            role_response.raise_for_status()
            role = str((role_response.json() or {}).get("role", "")).upper()
            logger.info(
                "project_discovery_role_resolved extra=%s",
                {"pod_id": pod_id, "status_code": role_response.status_code, "role": role},
            )
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
            logger.exception(
                "project_discovery_role_lookup_failed extra=%s",
                {"pod_id": pod_id, "api_url": api_url, "error_type": type(exc).__name__},
            )
    logger.info(
        "project_discovery_completed extra=%s",
        {"candidate_count": candidate_count, "instance_count": len(instances)},
    )
    return instances
