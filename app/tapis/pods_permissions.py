"""Helpers for deriving user roles from Tapis Pods permissions."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse

from tapipy.errors import BaseTapyException  # type: ignore[import-untyped]
from tapipy.tapis import Tapis  # type: ignore[import-untyped]

from app.core.config import Settings

logger = logging.getLogger(__name__)


POD_ROLE_ORDER = {"READ": 0, "USER": 1, "ADMIN": 2}


@dataclass(slots=True)
class PodRoleResult:
    role: str | None
    permissions: Sequence[str] | None


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.strip()
    return stripped or None


def _derive_pods_base_url(settings: Settings) -> str | None:
    pods_base = _clean(settings.TAPIS_PODS_BASE_URL)
    if pods_base:
        return pods_base.rstrip("/")

    tapis_base = _clean(settings.TAPIS_BASE_URL)
    if not tapis_base:
        return None

    try:
        parsed = urlparse(tapis_base)
        host = parsed.hostname
        if not host:
            return None
        pods_host = host if host.startswith("pods.") else f"pods.{host}"
        netloc = pods_host
        if parsed.port:
            netloc = f"{pods_host}:{parsed.port}"
        return f"{parsed.scheme}://{netloc}"
    except Exception:  # pragma: no cover - defensive fallback
        logger.debug("Failed to derive pods base URL from %s", tapis_base, exc_info=True)
        return None


def _resolve_target_pod_id(settings: Settings) -> str | None:
    explicit = _clean(settings.TAPIS_POD_ID) or _clean(os.getenv("TAPIS_POD_ID")) or _clean(os.getenv("POD_ID"))
    if explicit:
        return explicit
    return _derive_pod_id_from_config(settings)


def _build_user_variants(username: str | None) -> set[str]:
    if not username:
        return set()
    lowered = username.strip().lower()
    if not lowered:
        return set()
    variants: set[str] = {lowered}
    for delimiter in ("@", "/", "|", "\\"):
        if delimiter in lowered:
            for part in lowered.split(delimiter):
                part_clean = part.strip()
                if part_clean:
                    variants.add(part_clean)
    return variants


def _parse_permission_entry(entry: Any) -> tuple[str | None, str | None]:
    if isinstance(entry, str):
        if ":" in entry:
            user, level = entry.split(":", 1)
        else:
            user, level = entry, None
        return user or None, (level or None)

    if isinstance(entry, dict):
        user_candidate = entry.get("user") or entry.get("username")
        level_candidate = entry.get("level") or entry.get("permission") or entry.get("role")
        user: str | None = str(user_candidate) if user_candidate is not None else None
        level: str | None = str(level_candidate) if level_candidate is not None else None
        return user, level

    return None, None


def _select_role_for_user(username: str, permissions: Iterable[Any]) -> str | None:
    user_variants = _build_user_variants(username)
    if not user_variants:
        return None

    best_role: str | None = None
    best_rank = -1

    for entry in permissions:
        perm_user, perm_role = _parse_permission_entry(entry)
        if not perm_user or not perm_role:
            continue

        normalized_user = perm_user.strip().lower()
        if normalized_user not in user_variants:
            continue

        normalized_role = perm_role.strip().upper()
        role_rank = POD_ROLE_ORDER.get(normalized_role, -1)
        if role_rank > best_rank:
            best_role = normalized_role
            best_rank = role_rank

    return best_role


def _extract_permissions_from_response(response: Any) -> Sequence[str]:
    if response is None:
        return []

    result = getattr(response, "result", response)
    permissions = getattr(result, "permissions", None)
    if permissions is None and isinstance(result, dict):
        permissions = result.get("permissions")
    if isinstance(permissions, list):
        return permissions
    return []


def determine_user_role_from_pods(
    *,
    username: str,
    access_token: str | None,
    settings: Settings,
) -> PodRoleResult:
    """
    Resolve the highest pod permission level for ``username``.

    When pods integration is disabled or missing configuration this function
    returns ``PodRoleResult(role=None, permissions=None)`` so callers can fall
    back to the default role semantics for their environment.
    """

    pods_base_url = _derive_pods_base_url(settings)
    pod_id = _resolve_target_pod_id(settings)

    if not access_token or not pods_base_url or not pod_id:
        return PodRoleResult(role=None, permissions=None)

    try:
        client = Tapis(
            base_url=pods_base_url,
            tenant_id=settings.TAPIS_TENANT_ID,
            access_token=access_token,
        )
        response = client.pods.get_pod_permissions(pod_id=pod_id)
    except BaseTapyException as exc:  # pragma: no cover - dependency behaviour
        logger.info(
            "Unable to fetch Pods permissions for %s (pod=%s): %s",
            username,
            pod_id,
            exc,
        )
        return PodRoleResult(role=None, permissions=None)
    except Exception:  # pragma: no cover - defensive fallback
        logger.exception("Unexpected error while fetching Pods permissions for %s", username)
        return PodRoleResult(role=None, permissions=None)

    permissions = _extract_permissions_from_response(response)
    resolved_role = _select_role_for_user(username, permissions)
    return PodRoleResult(role=resolved_role, permissions=permissions)
def _derive_pod_id_from_config(settings: Settings) -> str | None:
    candidates = [
        getattr(settings, "API_BASE_URL", None),
        os.getenv("API_BASE_URL"),
        getattr(settings, "VITE_UPSTREAM_API_URL", None),
        os.getenv("VITE_UPSTREAM_API_URL"),
        getattr(settings, "UI_BASE_URL", None),
        os.getenv("UI_BASE_URL"),
        getattr(settings, "DATABASE_URL", None),
        os.getenv("DATABASE_URL"),
    ]
    for candidate in candidates:
        pod_id = _extract_pod_id_from_value(candidate)
        if pod_id:
            return pod_id
    return None


def _extract_pod_id_from_value(value: str | None) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None

    host: str | None = None
    try:
        parsed = urlparse(cleaned)
    except ValueError:
        parsed = None

    if parsed and parsed.scheme:
        host = parsed.hostname
    if not host and "@" in cleaned:
        host = cleaned.split("@", 1)[1].split("/", 1)[0]
    if not host and "//" not in cleaned:
        host = cleaned

    return _extract_pod_id_from_host(host)


def _extract_pod_id_from_host(host: str | None) -> str | None:
    hostname = _clean(host)
    if not hostname:
        return None
    lower_host = hostname.lower()
    if ".pods." in lower_host:
        return lower_host.split(".pods.", 1)[0]
    return None
