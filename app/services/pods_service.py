from __future__ import annotations

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

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Tapis-Token": self._token,
            "Accept": "application/json",
        }

    def _request(self, *, method: str, path: str, json: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = requests.request(method=method, url=url, headers=self._headers(), json=json, timeout=30)
        if not response.ok:
            logger.error("Pods API request failed (%s %s): %s %s", method, url, response.status_code, response.text)
            raise RuntimeError(response.text or f"Pods API request failed ({response.status_code})")
        return cast(Dict[str, Any], response.json())

    def create_volume(self, *, volume_id: str, description: str) -> Dict[str, Any]:
        payload = {"volume_id": volume_id, "description": description}
        return self._request(method="POST", path="/v3/pods/volumes", json=payload)

    def create_pod(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = dict(payload)
        sanitized.pop("pod_template", None)
        logger.debug("Creating pod %s with keys: %s", sanitized.get("pod_id"), list(sanitized.keys()))
        return self._request(method="POST", path="/v3/pods", json=sanitized)

    def build_bundle(self, *, base: str, pg_user: str, pg_password: str) -> Dict[str, Any]:
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
                volume_id: {
                    "type": "tapisvolume",
                    "mount_path": "/var/lib/postgresql/data",
                    "sub_path": "",
                }
            },
            "time_to_stop_default": -1,
            "networking": {
                "default": {
                    "protocol": "postgres",
                    "port": 5432,
                    "url": f"{base_clean}postgres.pods.tacc.tapis.io",
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

        api_payload = {
            "pod_id": f"{base_clean}api",
            "image": "ghcr.io/wmobley/upstream-docker-pods:main",
            "description": "Upstream API connected to postgres pod",
            "command": [
                "/bin/bash",
                "-c",
                "alembic upgrade heads && uvicorn app.main:app --reload --host 0.0.0.0",
            ],
            "environment_variables": {
                "DATABASE_URL": f"postgresql+psycopg://{pg_user}:{pg_password}@{base_clean}postgres.pods.tacc.tapis.io:443/{pg_user}",
                "VITE_UPSTREAM_API_URL": f"https://{base_clean}.pods.tacc.tapis.io",
                "POSTGRES_PASSWORD": pg_password,
                "TAS_USER": self.settings.TAS_USER,
                "TAS_SECRET": self.settings.TAS_SECRET,
                "JWT_SECRET": self.settings.JWT_SECRET,
                "ALG": self.settings.ALG,
                "TAS_URL": self.settings.TAS_URL,
                "ENVIRONMENT": self.settings.ENVIRONMENT,
                "ENV": self.settings.ENV,
                "CKAN_URL": self.settings.CKAN_URL,
                "CKAN_TIMEOUT": str(self.settings.CKAN_TIMEOUT),
                "CKAN_ORGANIZATION": self.settings.CKAN_ORGANIZATION or "upstream",
                "CKAN_ADMIN_USERNAME": self.settings.CKAN_ADMIN_USERNAME or "dso_test",
                "CKAN_ADMIN_API_KEY": self.settings.CKAN_ADMIN_API_KEY or "",
                "UI_BASE_URL": f"https://{base_clean}.pods.tacc.tapis.io",
                "API_BASE_URL": f"https://{base_clean}api.pods.tacc.tapis.io",
            },
            "status_requested": "ON",
            "volume_mounts": {},
            "time_to_stop_default": -1,
            "networking": {
                "default": {
                    "protocol": "http",
                    "port": 8000,
                    "url": f"{base_clean}api.pods.tacc.tapis.io",
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

        ui_payload = {
            "pod_id": base_clean,
            "image": "ghcr.io/wmobley/upstream-ui-pods:main",
            "description": "Upstream UI frontend",
            "environment_variables": {
                "VITE_UPSTREAM_API_URL": f"https://{base_clean}api.pods.tacc.tapis.io",
                "VITE_CKAN_URL": self.settings.CKAN_URL,
                "VITE_TAPIS_BASE_URL": self.settings.TAPIS_BASE_URL,
                "VITE_TAPIS_PODS_BASE_URL": self.settings.TAPIS_BASE_URL,
            },
            "status_requested": "ON",
            "volume_mounts": {},
            "time_to_stop_default": -1,
            "networking": {
                "default": {
                    "protocol": "http",
                    "port": 80,
                    "url": f"{base_clean}.pods.tacc.tapis.io",
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

        created = {
            "volume": self.create_volume(volume_id=volume_id, description=f"Volume for {base_clean}"),
            "postgres": self.create_pod(postgres_payload),
            "api": self.create_pod(api_payload),
            "ui": self.create_pod(ui_payload),
        }
        return created


__all__ = ["PodsService", "_sanitize_base"]
