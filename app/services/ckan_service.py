from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Literal, Optional, cast

import requests

from app.core.config import get_settings


logger = logging.getLogger(__name__)

CKANAuthMode = Literal["combined", "bearer", "x_tapis"]


def _mask_token(token: str | None) -> dict[str, int | str | None]:
    if not token:
        return {"length": None, "dots": None, "prefix": None, "suffix": None}
    normalized = token
    if normalized.lower().startswith("bearer "):
        normalized = normalized.split(" ", 1)[1]
    return {
        "length": len(normalized),
        "dots": normalized.count("."),
        "prefix": normalized[:16],
        "suffix": normalized[-16:],
    }


class CKANError(RuntimeError):
    """Raised when CKAN returns an error response."""


def _slugify(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "-")
    slug = []
    for char in normalized:
        if char.isalnum() or char in {"-", "_"}:
            slug.append(char)
        elif char in {"/", ":"}:
            slug.append("-")
    result = "".join(slug).strip("-")
    return result or "dataset"


class CKANService:
    def __init__(self, *, base_url: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(
        self,
        token: str,
        *,
        as_api_key: bool = False,
        auth_mode: CKANAuthMode = "combined",
    ) -> Dict[str, str]:
        if as_api_key:
            return {
                "Authorization": token,
                "Content-Type": "application/json",
            }
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
        }
        if auth_mode in {"combined", "bearer"}:
            headers["Authorization"] = f"Bearer {token}"
        if auth_mode in {"combined", "x_tapis"}:
            headers["X-Tapis-Token"] = token
        return headers

    def _request(
        self,
        *,
        method: str,
        path: str,
        token: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        as_api_key: bool = False,
        auth_mode: CKANAuthMode = "combined",
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers = self._headers(token, as_api_key=as_api_key, auth_mode=auth_mode)
        logger.info(
            "CKAN outbound request extra=%s",
            {
                "method": method,
                "url": url,
                "auth_mode": auth_mode,
                "as_api_key": as_api_key,
                "authorization": _mask_token(headers.get("Authorization")),
                "x_tapis_token": _mask_token(headers.get("X-Tapis-Token")),
                "json_keys": sorted(json.keys()) if isinstance(json, dict) else None,
                "param_keys": sorted(params.keys()) if isinstance(params, dict) else None,
            },
        )
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=json,
            params=params,
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            logger.error(
                "CKAN request failed (%s %s) status=%s body=%s",
                method,
                url,
                response.status_code,
                response.text,
            )
            raise CKANError(response.text) from exc

        payload: Dict[str, Any] = response.json()
        if not payload.get("success", False):
            logger.error("CKAN request returned success=false (%s %s): %s", method, url, payload)
            raise CKANError(str(payload.get("error", "unknown error")))
        return payload["result"]

    def list_user_organizations(
        self,
        *,
        token: str,
        auth_mode: CKANAuthMode = "combined",
    ) -> List[Dict[str, Any]]:
        result = self._request(
            method="GET",
            path="/api/3/action/organization_list_for_user",
            token=token,
            params={"all_fields": True},
            auth_mode=auth_mode,
        )
        if not isinstance(result, list):
            raise CKANError("Unexpected CKAN response format for organization list")
        organizations: List[Dict[str, Any]] = [
            cast(Dict[str, Any], org) for org in result if isinstance(org, dict)
        ]
        return organizations

    def debug_organization_lookup(self, *, token: str) -> Dict[str, Any]:
        results: Dict[str, Any] = {}
        for auth_mode in ("combined", "bearer", "x_tapis"):
            try:
                organizations = self.list_user_organizations(token=token, auth_mode=auth_mode)
                results[auth_mode] = {
                    "success": True,
                    "organization_count": len(organizations),
                    "organizations": organizations,
                }
            except CKANError as exc:
                results[auth_mode] = {
                    "success": False,
                    "error": str(exc),
                }
        return results

    def get_organization(
        self,
        *,
        token: str,
        organization_id: str,
        include_users: bool = False,
        auth_mode: CKANAuthMode = "combined",
    ) -> Dict[str, Any]:
        result = self._request(
            method="GET",
            path="/api/3/action/organization_show",
            token=token,
            params={"id": organization_id, "include_users": include_users},
            auth_mode=auth_mode,
        )
        if not isinstance(result, dict):
            raise CKANError("Unexpected CKAN response format for organization")
        return cast(Dict[str, Any], result)

    def user_is_in_organization(
        self,
        *,
        token: str,
        organization_id: str,
        username: str,
        auth_mode: CKANAuthMode = "combined",
    ) -> bool:
        organization = self.get_organization(
            token=token,
            organization_id=organization_id,
            include_users=True,
            auth_mode=auth_mode,
        )
        users = organization.get("users", [])
        if not isinstance(users, list):
            raise CKANError("Unexpected CKAN response format for organization users")
        normalized_username = username.strip().lower()
        for user in users:
            if not isinstance(user, dict):
                continue
            candidate = str(user.get("name") or "").strip().lower()
            if candidate == normalized_username:
                return True
        return False

    def get_dataset(self, *, token: str, name_or_id: str) -> Dict[str, Any]:
        result = self._request(
            method="GET",
            path="/api/3/action/package_show",
            token=token,
            params={"id": name_or_id},
        )
        if not isinstance(result, dict):
            raise CKANError("Unexpected CKAN response format for dataset")
        return cast(Dict[str, Any], result)

    def create_or_update_dataset(
        self,
        *,
        token: str,
        name: str,
        title: str,
        owner_org: Optional[str],
        notes: str,
        tags: Iterable[str],
        extras: Iterable[Dict[str, str]],
        private: bool = True,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": name,
            "title": title,
            "owner_org": owner_org,
            "notes": notes,
            "private": private,
            "tags": [{"name": tag} for tag in tags],
            "extras": list(extras),
        }
        if extra_fields:
            payload.update(extra_fields)
        try:
            result = self._request(
                method="POST",
                path="/api/3/action/package_create",
                token=token,
                json=payload,
            )
            if not isinstance(result, dict):
                raise CKANError("Unexpected CKAN response format when creating dataset")
            return cast(Dict[str, Any], result)
        except CKANError as exc:
            message = str(exc).lower()
            should_patch = (
                "already exists" in message
                or "already in use" in message
                or "url is already" in message
            )
            if not should_patch:
                try:
                    self.get_dataset(token=token, name_or_id=name)
                except CKANError:
                    raise
                should_patch = True
            if not should_patch:
                raise
            payload["id"] = name
            result = self._request(
                method="POST",
                path="/api/3/action/package_patch",
                token=token,
                json=payload,
            )
            if not isinstance(result, dict):
                raise CKANError("Unexpected CKAN response format when updating dataset")
            return cast(Dict[str, Any], result)

    def ensure_dataset_visibility(self, *, token: str, dataset_id: str, private: bool) -> Dict[str, Any]:
        result = self._request(
            method="POST",
            path="/api/3/action/package_patch",
            token=token,
            json={"id": dataset_id, "private": private},
        )
        if not isinstance(result, dict):
            raise CKANError("Unexpected CKAN response format when updating visibility")
        return cast(Dict[str, Any], result)

    def delete_dataset(self, *, token: str, name_or_id: str, force: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"id": name_or_id}
        if force:
            payload["force"] = True
        result = self._request(
            method="POST",
            path="/api/3/action/package_delete",
            token=token,
            json=payload,
        )
        if not isinstance(result, dict):
            logger.error("Unexpected CKAN response format when deleting dataset %s: %s", name_or_id, result)
            raise CKANError("Unexpected CKAN response format when deleting dataset")
        return cast(Dict[str, Any], result)

    def ensure_resource(
        self,
        *,
        token: str,
        dataset_id: str,
        name: str,
        url: str,
        description: str,
        format_: str = "API",
        resource_id: str | None = None,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "package_id": dataset_id,
            "name": name,
            "url": url,
            "format": format_,
            "description": description,
        }
        if extra_fields:
            payload.update(extra_fields)

        if resource_id:
            payload["id"] = resource_id
            result = self._request(
                method="POST",
                path="/api/3/action/resource_update",
                token=token,
                json=payload,
            )
            if not isinstance(result, dict):
                raise CKANError("Unexpected CKAN response format when updating resource")
            return cast(Dict[str, Any], result)

        try:
            result = self._request(
                method="POST",
                path="/api/3/action/resource_create",
                token=token,
                json=payload,
            )
            if not isinstance(result, dict):
                raise CKANError("Unexpected CKAN response format when creating resource")
            return cast(Dict[str, Any], result)
        except CKANError:
            raise

    def ensure_user_in_organization(
        self,
        *,
        api_key: str,
        organization: str,
        username: str,
        role: str = "admin",
        requestor: str | None = None,
    ) -> Dict[str, Any]:
        payload = {
            "id": organization,
            "username": username,
            "role": role,
        }
        try:
            result = self._request(
                method="POST",
                path="/api/3/action/organization_member_create",
                token=api_key,
                json=payload,
                as_api_key=True,
            )
            logger.info(
                "CKAN membership ensured for %s in %s as %s (requested by %s)",
                username,
                organization,
                role,
                requestor or "unknown",
            )
            if not isinstance(result, dict):
                raise CKANError("Unexpected CKAN response format when adding organization member")
            return cast(Dict[str, Any], result)
        except CKANError as exc:
            lowered = str(exc).lower()
            if "already" in lowered and "member" in lowered:
                logger.info(
                    "CKAN reports %s already a member of %s (requested by %s)",
                    username,
                    organization,
                    requestor or "unknown",
                )
                return {"already_member": True}
            raise

    def find_datasets_by_extra(self, *, token: str, key: str, value: str, rows: int = 20) -> List[Dict[str, Any]]:
        fq_value = f'extras_{key}:"{value}"'
        result = self._request(
            method="GET",
            path="/api/3/action/package_search",
            token=token,
            params={"fq": fq_value, "rows": rows},
        )
        if not isinstance(result, dict):
            raise CKANError("Unexpected CKAN response format when searching datasets")
        datasets = result.get("results", [])
        if not isinstance(datasets, list):
            raise CKANError("Unexpected CKAN response format when searching datasets")
        return [cast(Dict[str, Any], dataset) for dataset in datasets if isinstance(dataset, dict)]


def get_ckan_service() -> CKANService | None:
    settings = get_settings()
    if not settings.CKAN_URL:
        return None
    return CKANService(base_url=settings.CKAN_URL, timeout=settings.CKAN_TIMEOUT)


__all__ = ["CKANService", "CKANError", "_slugify", "get_ckan_service"]
