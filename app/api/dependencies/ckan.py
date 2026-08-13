from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterable, List

from fastapi import Depends, HTTPException

from app.api.dependencies.auth import (
    get_current_user,
    get_viewer_user,
    get_tapis_token_header,
    get_tapis_token_header_optional,
)
from app.api.v1.schemas.user import User
from app.core.config import get_settings
from app.db.models.campaign import Campaign
from app.db.session import SessionLocal
from app.services.ckan_service import CKANError, get_ckan_service

logger = logging.getLogger(__name__)
settings = get_settings()

# Cache CKAN org lookups keyed by token to avoid a live CKAN call on every request.
# Entries expire after _CACHE_TTL_SECONDS seconds.
_CACHE_TTL_SECONDS = 300
_org_cache: dict[str, tuple[float, List[str]]] = {}


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped.lower() if stripped else None


def _org_identifiers(org: Dict[str, Any]) -> Iterable[str]:
    yield from filter(
        None,
        (
            _normalize(org.get("id")),
            _normalize(org.get("name")),
            _normalize(org.get("display_name") or org.get("title")),
        ),
    )


def _fetch_user_organizations(*, token: str, username: str, strict: bool = True) -> List[str]:
    cached = _org_cache.get(token)
    if cached is not None:
        expires_at, orgs = cached
        if time.monotonic() < expires_at:
            logger.debug("CKAN org cache hit for %s", username)
            return orgs
        del _org_cache[token]

    ckan_client = get_ckan_service()
    if not ckan_client or not settings.CKAN_URL:
        logger.debug("CKAN integration disabled; treating allocations as unrestricted for %s", username)
        return []

    try:
        organizations = ckan_client.list_user_organizations(token=token)
    except CKANError as exc:
        logger.warning("Failed to retrieve CKAN organizations for %s: %s", username, exc)
        if strict:
            raise HTTPException(status_code=502, detail="Unable to retrieve CKAN organizations.") from exc
        logger.info("Proceeding without allocation restrictions for %s due to CKAN error", username)
        return []

    identifiers: set[str] = set()
    for org in organizations:
        identifiers.update(filter(None, _org_identifiers(org)))
    result = sorted(identifiers)

    _org_cache[token] = (time.monotonic() + _CACHE_TTL_SECONDS, result)
    logger.debug("CKAN org cache populated for %s (%d orgs)", username, len(result))
    return result


def user_has_ckan_organization(
    *,
    token: str,
    username: str,
    organization: str,
) -> bool:
    ckan_client = get_ckan_service()
    if not ckan_client or not settings.CKAN_URL:
        return False

    try:
        return ckan_client.user_is_in_organization(
            token=token,
            organization_id=organization,
            username=username,
        )
    except CKANError as exc:
        logger.warning(
            "Fallback CKAN organization membership check failed for %s in %s: %s",
            username,
            organization,
            exc,
        )
        return False


async def get_user_allocations(
    current_user: User = Depends(get_viewer_user),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
) -> List[str]:
    """
    Strict variant for write/publish endpoints: a CKAN outage raises 502 so the
    request fails closed rather than mutating data without an allocation check.
    """
    return resolve_user_allocations(current_user, tapis_token)


async def get_user_allocations_optional(
    current_user: User = Depends(get_viewer_user),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
) -> List[str]:
    """
    Lenient variant for read-only endpoints: a CKAN outage falls back to
    unrestricted rather than blocking the request.
    """
    return resolve_user_allocations(current_user, tapis_token, strict=False)


def resolve_user_allocations(
    user: User | None, tapis_token: str | None, *, strict: bool = True
) -> List[str]:
    if not user or not tapis_token:
        return []
    return _fetch_user_organizations(token=tapis_token, username=user.username, strict=strict)


def check_allocation_permission(
    current_user: User,
    campaign_id: int,
    allocations: List[str],
) -> bool:
    """
    Ensure the current user has access to the campaign via CKAN organization membership.

    If CKAN integration is disabled or no allocations are provided, access is permitted.
    """
    normalized_allocations = {
        normalized
        for allocation in allocations
        if (normalized := _normalize(allocation))
    }
    if not normalized_allocations:
        return True

    with SessionLocal() as session:
        campaign_allocation_row = (
            session.query(Campaign.allocation)
            .filter(Campaign.campaignid == campaign_id)
            .first()
        )
        campaign_allocation = _normalize(
            campaign_allocation_row[0] if campaign_allocation_row else None
        )

    if campaign_allocation not in normalized_allocations:
        raise HTTPException(
            status_code=404,
            detail="Access to Campaign unavailable. Improper Allocation",
        )
    return True
