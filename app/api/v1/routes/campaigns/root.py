from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from app.api.dependencies.pytas import check_allocation_permission

from app.api.dependencies.auth import get_current_user_unified, get_current_user_unified_optional
from app.api.dependencies.pytas import get_allocations
from app.api.v1.schemas.campaign import (
    CampaignCreateResponse,
    GetCampaignResponse,
    ListCampaignsResponsePagination,
    CampaignsIn,
    CampaignUpdate,
    PublishRequest,
    PublishResponse,
)
from app.api.v1.schemas.user import User
from app.db.repositories.campaign_repository import CampaignRepository
from app.db.session import get_db
from app.services.campaign_service import CampaignService
from app.services.publishing_service import PublishingService


router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.post("")
async def create_campaign(
    campaign: CampaignsIn,
    current_user: User = Depends(get_current_user_unified),
    db: Session = Depends(get_db),
) -> CampaignCreateResponse:
    campaign_service = CampaignService(CampaignRepository(db))
    return campaign_service.create_campaign(campaign)


@router.get("")
async def list_campaigns(
    page: int = 1,
    limit: int = 20,
    bbox: Annotated[
        str | None,
        Query(description="Bounding box of the campaign west,south,east,north"),
    ] = None,
    start_date: Annotated[
        datetime | None,
        Query(description="Start date of the campaign", example="2024-01-01"),
    ] = None,
    end_date: Annotated[
        datetime | None,
        Query(description="End date of the campaign", example="2025-01-01"),
    ] = None,
    sensor_variables: Annotated[
        list[str] | None, Query(description="List of sensor variables to filter by")
    ] = None,
    current_user: User | None = Depends(get_current_user_unified_optional),
    db: Session = Depends(get_db),
) -> ListCampaignsResponsePagination:
    campaign_service = CampaignService(CampaignRepository(db))

    if current_user:
        # Authenticated user - show all campaigns they have access to
        allocations = get_allocations(current_user.username)
        results, total_count = campaign_service.get_campaigns_with_summary(
            allocations, bbox, start_date, end_date, sensor_variables, page, limit, published_only=False
        )
    else:
        # Unauthenticated user - show only published campaigns
        results, total_count = campaign_service.get_campaigns_with_summary(
            None, bbox, start_date, end_date, sensor_variables, page, limit, published_only=True
        )

    response = ListCampaignsResponsePagination(
        items=results,
        total=total_count,
        page=page,
        size=limit,
        pages=(total_count + limit - 1) // limit,
    )
    return response


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: int,
    current_user: User | None = Depends(get_current_user_unified_optional),
    db: Session = Depends(get_db),
) -> GetCampaignResponse:
    campaign_service = CampaignService(CampaignRepository(db))

    if current_user:
        # Authenticated user - check allocation permissions
        if not check_allocation_permission(current_user, campaign_id):
            raise HTTPException(status_code=404, detail="Campaign not found")
        campaign = campaign_service.get_campaign_with_summary(campaign_id, published_only=False)
    else:
        # Unauthenticated user - only show if published
        campaign = campaign_service.get_campaign_with_summary(campaign_id, published_only=True)

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.delete("/{campaign_id}", status_code=204)
def delete_sensor(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_unified),
) -> Response:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    campaign_repository = CampaignRepository(db)
    campaign_service = CampaignService(campaign_repository=campaign_repository)
    campaign_service.delete_campaign(campaign_id=campaign_id)
    return Response(status_code=204)


@router.put("/{campaign_id}", response_model=CampaignCreateResponse)
def update_campaign(
    campaign_id: int,
    campaign: CampaignsIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_unified),
) -> CampaignCreateResponse:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    campaign_service = CampaignService(CampaignRepository(db))
    updated_campaign = campaign_service.update_campaign(campaign_id, campaign)
    if not updated_campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return updated_campaign


@router.patch("/{campaign_id}", response_model=CampaignCreateResponse)
def partial_update_campaign(
    campaign_id: int,
    campaign: CampaignUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_unified),
) -> CampaignCreateResponse:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    campaign_service = CampaignService(CampaignRepository(db))
    updated_campaign = campaign_service.partial_update_campaign(campaign_id, campaign)
    if not updated_campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return updated_campaign


@router.post("/{campaign_id}/publish", response_model=PublishResponse)
def publish_campaign(
    campaign_id: int,
    publish_request: PublishRequest = PublishRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_unified),
) -> PublishResponse:
    """Publish a campaign with optional cascading to stations, sensors, and measurements."""
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")

    publishing_service = PublishingService(db)
    result = publishing_service.publish_campaign(
        campaign_id,
        cascade=publish_request.cascade,
        force=publish_request.force
    )
    return PublishResponse(**result)


@router.post("/{campaign_id}/unpublish", response_model=PublishResponse)
def unpublish_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_unified),
) -> PublishResponse:
    """Unpublish a campaign."""
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")

    publishing_service = PublishingService(db)
    result = publishing_service.unpublish_campaign(campaign_id)
    return PublishResponse(**result)
