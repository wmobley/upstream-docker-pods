from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from app.api.dependencies.pytas import check_allocation_permission

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.pytas import get_allocations
from app.api.v1.schemas.campaign import (
    CampaignCreateResponse,
    GetCampaignResponse,
    ListCampaignsResponsePagination,
    CampaignsIn,
    CampaignUpdate,
)
from app.api.v1.schemas.user import User
from app.db.repositories.campaign_repository import CampaignRepository
from app.db.session import get_db
from app.services.campaign_service import CampaignService


router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.post("")
async def create_campaign(
    campaign: CampaignsIn,
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ListCampaignsResponsePagination:
    allocations = get_allocations(current_user.username)
    campaign_service = CampaignService(CampaignRepository(db))
    results, total_count = campaign_service.get_campaigns_with_summary(
        allocations, bbox, start_date, end_date, sensor_variables, page, limit
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GetCampaignResponse:
    campaign_service = CampaignService(CampaignRepository(db))
    campaign = campaign_service.get_campaign_with_summary(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.delete("/{campaign_id}", status_code=204)
def delete_sensor(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
) -> CampaignCreateResponse:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    campaign_service = CampaignService(CampaignRepository(db))
    updated_campaign = campaign_service.partial_update_campaign(campaign_id, campaign)
    if not updated_campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return updated_campaign
