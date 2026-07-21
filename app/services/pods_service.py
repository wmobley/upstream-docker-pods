from __future__ import annotations

import copy
import logging
import re
from typing import Any, Dict, Optional, cast

import requests

from app.core.config import get_settings
from app.tapis import TapisAuthClient

logger = logging.getLogger(__name__)


def _sanitize_base(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]", "", value.strip().lower())
    if not cleaned:
        raise ValueError("Base name must contain letters or numbers")
    if not cleaned[0].isalpha():
        cleaned = f"v{cleaned}"
    return cleaned


class PodsService:
    def __init__(self, token_override: str | None = None) -> None:
        self.settings = get_settings()
        self.base_url = (self.settings.TAPIS_PODS_BASE_URL or self.settings.TAPIS_BASE_URL).rstrip("/")
        if token_override:
            self._token = token_override
        else:
            raise RuntimeError("Tapis token required to create pods bundle")

    def _fetch_service_token(self) -> str:
        username = self.settings.TAPIS_SERVICE_USERNAME or self.settings.TAS_USER
        password = self.settings.TAPIS_SERVICE_PASSWORD or self.settings.TAS_SECRET
        if not username or not password:
            raise RuntimeError("Tapis service credentials are not configured")
        client = TapisAuthClient(
            base_url=self.settings.TAPIS_BASE_URL,
            tenant_id=self.settings.TAPIS_TENANT_ID,
        )
        result = client.authenticate(username, password)
        if not result.tokens or not result.tokens.get("access_token"):
            raise RuntimeError(f"Failed to obtain Tapis token for service user {username}")
        return cast(str, result.tokens["access_token"])

    def _headers(self, token: str | None = None) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Tapis-Token": token or self._token,
            "Accept": "application/json",
        }

    def _request(
        self, *, method: str, path: str, json: Dict[str, Any] | None = None, token: str | None = None
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = requests.request(method=method, url=url, headers=self._headers(token), json=json, timeout=30)
        if not response.ok:
            logger.error("Pods API request failed (%s %s): %s %s", method, url, response.status_code, response.text)
            raise RuntimeError(response.text or f"Pods API request failed ({response.status_code})")
        return cast(Dict[str, Any], response.json())

    def create_stack(self, *, stack_id: str, description: str = "") -> Dict[str, Any]:
        payload = {"stack_id": stack_id, "description": description}
        try:
            return self._request(method="POST", path="/v3/pods/stacks", json=payload)
        except RuntimeError as exc:
            message = str(exc).lower()
            if "already exists" in message or "uniqueviolation" in message:
                logger.info("Stack %s already exists; continuing.", stack_id)
                return {"status": "exists", "stack_id": stack_id}
            # Tapis Pods server bug: stack is created but response serialization fails.
            if "responsevalidationerror" in message:
                logger.warning("Stack %s created but server returned ResponseValidationError; continuing.", stack_id)
                return {"status": "created", "stack_id": stack_id}
            raise

    def create_volume(self, *, volume_id: str, description: str) -> Dict[str, Any]:
        payload = {"volume_id": volume_id, "description": description}
        try:
            return self._request(method="POST", path="/v3/pods/volumes", json=payload)
        except RuntimeError as exc:
            message = str(exc).lower()
            # Treat "already exists" as success so bundle creation is idempotent.
            if "already exists" in message and "volume" in message:
                logger.info("Volume %s already exists; continuing.", volume_id)
                return {"status": "exists", "volume_id": volume_id}
            raise

    def set_volume_permission(self, *, volume_id: str, user: str, level: str = "ADMIN") -> Dict[str, Any]:
        payload = {"user": user, "level": level}
        return self._request(method="POST", path=f"/v3/pods/volumes/{volume_id}/permissions", json=payload)

    def create_pod(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = dict(payload)
        sanitized.pop("pod_template", None)
        logger.debug("Creating pod %s with keys: %s", sanitized.get("pod_id"), list(sanitized.keys()))
        try:
            return self._request(method="POST", path="/v3/pods", json=sanitized)
        except RuntimeError as exc:
            message = str(exc)
            lowered = message.lower()
            # Treat "already exists" as success so bundle creation is idempotent,
            # matching create_stack()/create_volume()'s behavior — otherwise retrying
            # a partially-completed bundle hard-fails on pods left over from an
            # earlier attempt.
            if "already exists" in lowered or "uniqueviolation" in lowered:
                pod_id = sanitized.get("pod_id")
                logger.info("Pod %s already exists; continuing.", pod_id)
                return {"status": "exists", "pod_id": pod_id}

            mount_path_rejected = (
                "volume_mounts" in message
                and "mount_path" in message
                and "Extra inputs are not permitted" in message
            )
            source_id_required = (
                "volume_mounts" in message
                and "requires source_id" in message
            )
            mount_path_key_required = (
                "volume_mounts" in message
                and "mount_path must be an absolute path starting with '/'" in message
            )
            if not (mount_path_rejected or source_id_required or mount_path_key_required):
                raise

            compatibility_payload = copy.deepcopy(sanitized)
            volume_mounts = compatibility_payload.get("volume_mounts")
            if isinstance(volume_mounts, dict):
                normalized_mounts: Dict[str, Any] = {}
                for mount_name, mount_cfg in volume_mounts.items():
                    if not isinstance(mount_cfg, dict):
                        normalized_mounts[mount_name] = mount_cfg
                        continue
                    mount_cfg_copy = dict(mount_cfg)
                    mount_path = mount_cfg_copy.get("mount_path")
                    if mount_cfg_copy.get("type") == "tapisvolume" and not mount_cfg_copy.get("source_id"):
                        mount_cfg_copy["source_id"] = mount_name
                    if mount_path_rejected or mount_path_key_required:
                        mount_cfg_copy.pop("mount_path", None)

                    mount_key = mount_name
                    if isinstance(mount_path, str) and mount_path.startswith("/"):
                        mount_key = mount_path
                    normalized_mounts[mount_key] = mount_cfg_copy
                compatibility_payload["volume_mounts"] = normalized_mounts

            logger.warning(
                "Pods rejected volume_mounts payload for pod %s; retrying create with compatibility mapping.",
                sanitized.get("pod_id"),
            )
            return self._request(method="POST", path="/v3/pods", json=compatibility_payload)

    def set_pod_permission(self, *, pod_id: str, user: str, level: str = "ADMIN") -> Dict[str, Any]:
        payload = {"user": user, "level": level}
        return self._request(method="POST", path=f"/v3/pods/{pod_id}/permissions", json=payload)

    def set_stack_permission(self, *, stack_id: str, user: str, level: str = "ADMIN") -> Dict[str, Any]:
        payload = {"user": user, "level": level}
        return self._request(method="POST", path=f"/v3/pods/stacks/{stack_id}/permissions", json=payload)

    def grant_default_admin_permissions(
        self,
        *,
        stack_id: str | None = None,
        volume_id: str,
        pod_ids: list[str],
    ) -> dict[str, Any]:
        admin_users = [user for user in (self.settings.DEFAULT_ADMIN_USERS or []) if user]
        grants: dict[str, Any] = {"stack": {}, "volume": {}, "pods": {}}
        for user in admin_users:
            if stack_id:
                grants["stack"][user] = self.set_stack_permission(stack_id=stack_id, user=user, level="ADMIN")
            grants["volume"][user] = self.set_volume_permission(volume_id=volume_id, user=user, level="ADMIN")
            for pod_id in pod_ids:
                pod_grants = grants["pods"].setdefault(pod_id, {})
                pod_grants[user] = self.set_pod_permission(pod_id=pod_id, user=user, level="ADMIN")
        return grants

    def _bootstrap_pod_cors(self, *, pod_id: str, cors_config: Dict[str, Any]) -> Dict[str, Any]:
        """Grant the service account APPROVEDADMIN on pod_id, then set its CORS config.

        Uses the service account's own token, not the calling user's, since only the
        service account is pre-approved (per-pod) to self-grant APPROVEDADMIN. This is
        best-effort: any failure is logged and reported via the returned status rather
        than raised, so bundle creation still succeeds even if CORS bootstrap fails.
        """
        try:
            service_token = self._fetch_service_token()
        except RuntimeError as exc:
            logger.warning("CORS bootstrap for %s: could not obtain service token: %s", pod_id, exc)
            return {"status": "pending_manual_approval", "error": str(exc)}

        service_username = self.settings.TAPIS_SERVICE_USERNAME or self.settings.TAS_USER

        try:
            self._request(
                method="POST",
                path=f"/v3/pods/{pod_id}/permissions",
                json={"user": service_username, "level": "APPROVEDADMIN"},
                token=service_token,
            )
            logger.info("CORS bootstrap for %s: granted APPROVEDADMIN to %s.", pod_id, service_username)
        except RuntimeError as exc:
            logger.warning("CORS bootstrap for %s: APPROVEDADMIN grant failed: %s", pod_id, exc)
            return {"status": "pending_manual_approval", "error": str(exc)}

        try:
            self._request(
                method="PUT",
                path=f"/v3/pods/{pod_id}",
                json={"networking": {"default": cors_config}},
                token=service_token,
            )
            logger.info("CORS bootstrap for %s: CORS configured.", pod_id)
        except RuntimeError as exc:
            logger.warning("CORS bootstrap for %s: CORS PUT failed: %s", pod_id, exc)
            return {"status": "pending_manual_approval", "error": str(exc)}

        return {"status": "configured"}

    def build_bundle(self, *, base: str, pg_user: str, pg_password: str, display_name: str = "", description: str = "") -> Dict[str, Any]:
        base_clean = _sanitize_base(base)
        volume_id = f"{base_clean}volume"

        postgres_payload = {
            "pod_id": f"{base_clean}postgres",
            "image": "postgis/postgis:17-3.5",
            "description": "postgres for upstream-docker",
            "command": ["docker-entrypoint.sh"],
            "arguments": [
                "-c",
                "ssl=on",
                "-c",
                "ssl_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem",
                "-c",
                "ssl_key_file=/etc/ssl/private/ssl-cert-snakeoil.key",
            ],
            "environment_variables": {
                "POSTGRES_USER": pg_user,
                "POSTGRES_PASSWORD": pg_password,
                "POSTGRES_DB": pg_user,
            },
            "status_requested": "ON",
            "volume_mounts": {
                "/var/lib/postgresql/data": {
                    "type": "tapisvolume",
                    "source_id": volume_id,
                    "sub_path": "",
                }
            },
            "time_to_stop_default": -1,
            "networking": {
                "default": {
                    "protocol": "postgres",
                    "port": 5432,
                    "url": f"{base_clean}postgres.pods.portals.tapis.io",
                }
            },
            "resources": {
                "cpu_request": 250,
                "cpu_limit": 2000,
                "mem_request": 256,
                "mem_limit": 3072,
                "gpus": 0,
            },
        }

        friendly_name = display_name.strip() or description.strip() or base_clean
        ui_origin = self.settings.UI_BASE_URL.rstrip("/")

        api_payload = {
            "pod_id": f"{base_clean}api",
            "image": "ghcr.io/wmobley/upstream-docker-pods:main",
            "description": f"[upstream] {friendly_name}",
            "stack_id": base_clean,
            "command": [
                "/bin/bash",
                "-c",
                "until alembic upgrade heads; do echo 'DB not ready, retrying in 10s...'; sleep 10; done && uvicorn app.main:app --reload --host 0.0.0.0",
            ],
            "environment_variables": {
                "DATABASE_URL": f"postgresql+psycopg://{pg_user}:{pg_password}@{base_clean}postgres.pods.portals.tapis.io:443/{pg_user}",
                "POSTGRES_PASSWORD": pg_password,
                "TAS_USER": self.settings.TAS_USER,
                "TAS_SECRET": self.settings.TAS_SECRET,
                "JWT_SECRET": self.settings.JWT_SECRET,
                "ALG": self.settings.ALG,
                "TAS_URL": self.settings.TAS_URL,
                "ENVIRONMENT": self.settings.ENVIRONMENT,
                "ENV": self.settings.ENV,
                "TAPIS_BASE_URL": self.settings.TAPIS_BASE_URL,
                "TAPIS_TENANT_ID": self.settings.TAPIS_TENANT_ID,
                "CKAN_URL": self.settings.CKAN_URL,
                "CKAN_TIMEOUT": str(self.settings.CKAN_TIMEOUT),
                "CKAN_ORGANIZATION": self.settings.CKAN_ORGANIZATION or "upstream",
                "CKAN_ADMIN_USERNAME": self.settings.CKAN_ADMIN_USERNAME or "dso_test",
                "CKAN_ADMIN_API_KEY": self.settings.CKAN_ADMIN_API_KEY or "",
                "UI_BASE_URL": f"https://{base_clean}.pods.portals.tapis.io",
                "API_BASE_URL": f"https://{base_clean}api.pods.portals.tapis.io",
            },
            "status_requested": "ON",
            "volume_mounts": {},
            "time_to_stop_default": -1,
            "networking": {
                "default": {
                    "protocol": "http",
                    "port": 8000,
                    "url": f"{base_clean}api.pods.portals.tapis.io",
                }
            },
            "resources": {
                "cpu_request": 250,
                "cpu_limit": 2000,
                "mem_request": 256,
                "mem_limit": 3072,
                "gpus": 0,
            },
        }

        # CORS is configured via a follow-up PUT (see _bootstrap_pod_cors), not the
        # create payload above: Tapis Pods gates any write to networking.<key>.cors_*
        # behind an APPROVEDADMIN permission that the creating user's own token
        # never holds. The service account is pre-approved to self-grant
        # APPROVEDADMIN per-pod, so it performs the grant + CORS PUT after creation.
        # Allow both the shared unified UI (UI_BASE_URL) and this bundle's own
        # per-base origin, plus the general tapis.io wildcard.
        api_cors_config = {
            "protocol": "http",
            "port": 8000,
            "url": f"{base_clean}api.pods.portals.tapis.io",
            "cors_allow_origins": [
                ui_origin,
                f"https://{base_clean}.pods.portals.tapis.io",
                "https://*.tapis.io",
            ],
            "cors_allow_methods": ["GET", "POST", "OPTIONS", "DELETE", "PUT", "HEAD", "PATCH"],
            "cors_allow_headers": [
                "content-type",
                "authorization",
                "x-tapis-token",
                "x-tapis-tenant",
                "x-tapis-username",
                "x-tapis-site",
            ],
            "cors_allow_credentials": False,
        }

        created = {
            "stack": self.create_stack(stack_id=base_clean, description=description or base_clean),
            "volume": self.create_volume(volume_id=volume_id, description=f"Volume for {base_clean}"),
            "postgres": self.create_pod(postgres_payload),
            "api": self.create_pod(api_payload),
        }
        # Grant admin permissions (using the creating user's own token, which owns
        # the new pod) before the CORS bootstrap step: the service account has no
        # access at all to a pod it didn't create, and Tapis rejects
        # POST /pods/{pod_id}/permissions from a caller with zero existing
        # permission on that pod — not just a missing APPROVEDADMIN tier. If the
        # service account is among DEFAULT_ADMIN_USERS, this grant is what gives
        # it the baseline access it needs before it can self-elevate.
        created["permissions"] = self.grant_default_admin_permissions(
            stack_id=base_clean,
            volume_id=volume_id,
            pod_ids=[f"{base_clean}postgres", f"{base_clean}api"],
        )
        created["cors"] = self._bootstrap_pod_cors(
            pod_id=f"{base_clean}api",
            cors_config=api_cors_config,
        )
        return created


__all__ = ["PodsService", "_sanitize_base"]
