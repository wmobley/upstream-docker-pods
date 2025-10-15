from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any

from app.api.dependencies.auth import get_current_user_unified
from app.db.session import get_db
from app.api.dependencies.pytas import check_allocation_permission
from app.api.v1.schemas.user import User

router = APIRouter()


@router.get("/campaigns/{campaign_id}/permissions")
def get_campaign_permissions(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_unified),
) -> dict[str, Any]:
    """
    Get user permissions for a specific campaign.
    Returns what actions the current user can perform on the campaign.
    """
    # Since allocations are removed, all authenticated users have full access
    has_access = True

    return {
        "campaign_id": campaign_id,
        "permissions": {
            "can_view": has_access,
            "can_edit": has_access,
            "can_delete": has_access,
            "can_create_stations": has_access,
            "can_delete_stations": has_access,
            "can_create_sensors": has_access,
            "can_delete_sensors": has_access,
        }
    }