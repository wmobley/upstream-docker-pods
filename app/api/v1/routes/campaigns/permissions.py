from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any

from app.api.dependencies.auth import get_current_user
from app.db.session import get_db
from app.api.dependencies.pytas import check_allocation_permission
from app.api.v1.schemas.user import User

router = APIRouter()


@router.get("/campaigns/{campaign_id}/permissions")
def get_campaign_permissions(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Get user permissions for a specific campaign.
    Returns what actions the current user can perform on the campaign.
    """
    # Check if user has access to this campaign
    has_access = check_allocation_permission(current_user, campaign_id)

    # In the current system, if you have access, you can delete
    # This can be extended in the future for more granular permissions
    can_delete = has_access
    can_edit = has_access
    can_view = has_access

    return {
        "campaign_id": campaign_id,
        "permissions": {
            "can_view": can_view,
            "can_edit": can_edit,
            "can_delete": can_delete,
            "can_create_stations": has_access,
            "can_delete_stations": can_delete,
            "can_create_sensors": has_access,
            "can_delete_sensors": can_delete,
        }
    }