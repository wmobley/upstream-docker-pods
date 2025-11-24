from __future__ import annotations

import logging
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


def _fetch_user_organizations(*, token: str, username: str) -> List[str]:
    ckan_client = get_ckan_service()
    if not ckan_client or not settings.CKAN_URL:
        logger.debug("CKAN integration disabled; treating allocations as unrestricted for %s", username)
        return []

    try:
        organizations = ckan_client.list_user_organizations(token=token)
    except CKANError as exc:
        logger.warning("Failed to retrieve CKAN organizations for %s: %s", username, exc)
        raise HTTPException(status_code=502, detail="Unable to retrieve CKAN organizations.") from exc

    identifiers: set[str] = set()
    for org in organizations:
        identifiers.update(filter(None, _org_identifiers(org)))
    return sorted(identifiers)


async def get_user_allocations(
    current_user: User = Depends(get_viewer_user),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
) -> List[str]:
    """
    Resolve allowed allocations dynamically from the CKAN organizations the user belongs to.
    """
    return resolve_user_allocations(current_user, tapis_token)


def resolve_user_allocations(user: User | None, tapis_token: str | None) -> List[str]:
    if not user or not tapis_token:
        return []
    return _fetch_user_organizations(token=tapis_token, username=user.username)


def check_allocation_permission(
    current_user: User,
    campaign_id: int,
    allocations: List[str],
) -> bool:
    """
    Ensure the current user has access to the campaign via CKAN organization membership.

    If CKAN integration is disabled or no allocations are provided, access is permitted.
    """
    if not allocations:
        return True

    with SessionLocal() as session:
        campaign_exists = (
            session.query(Campaign.campaignid)
            .filter(Campaign.campaignid == campaign_id)
            .filter(Campaign.allocation.in_(allocations))
            .first()
        )

    if not campaign_exists:
        raise HTTPException(
            status_code=404,
            detail="Access to Campaign unavailable. Improper Allocation",
        )
    return True
