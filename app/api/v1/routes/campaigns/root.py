import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session
from app.api.dependencies.pytas import (
    check_allocation_permission,
    get_user_allocations,
    get_user_allocations_optional,
)

from app.api.dependencies.auth import (
    get_viewer_user,
    get_edit_user,
    get_oauth_token_optional,
    get_tapis_token_header,
    get_tapis_token_header_optional,
)
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
from app.db.repositories.metadata_schema_repository import MetadataSchemaRepository
from app.db.repositories.station_repository import StationRepository
from app.db.session import get_db
from app.services.campaign_service import CampaignService
from app.services.metadata_schema_service import MetadataSchemaService
from pydantic import BaseModel


router = APIRouter(prefix="/campaigns", tags=["campaigns"])
logger = logging.getLogger(__name__)


@router.post("")
async def create_campaign(
    campaign: CampaignsIn,
    current_user: User = Depends(get_edit_user),
    db: Session = Depends(get_db),
) -> CampaignCreateResponse:
    metadata_service = MetadataSchemaService(MetadataSchemaRepository(db))
    errors = metadata_service.validate_metadata("campaign", campaign.metadata)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
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
    current_user: User = Depends(get_viewer_user),
    allocations: list[str] = Depends(get_user_allocations_optional),
    db: Session = Depends(get_db),
) -> ListCampaignsResponsePagination:
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
    current_user: User = Depends(get_viewer_user),
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
    current_user: User = Depends(get_edit_user),
    allocations: list[str] = Depends(get_user_allocations),
) -> Response:
    if not check_allocation_permission(current_user, campaign_id, allocations):
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
    current_user: User = Depends(get_edit_user),
    allocations: list[str] = Depends(get_user_allocations),
) -> CampaignCreateResponse:
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    metadata_service = MetadataSchemaService(MetadataSchemaRepository(db))
    errors = metadata_service.validate_metadata("campaign", campaign.metadata)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
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
    current_user: User = Depends(get_edit_user),
    allocations: list[str] = Depends(get_user_allocations),
) -> CampaignCreateResponse:
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    metadata_service = MetadataSchemaService(MetadataSchemaRepository(db))
    errors = metadata_service.validate_metadata("campaign", campaign.metadata)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    campaign_service = CampaignService(CampaignRepository(db))
    updated_campaign = campaign_service.partial_update_campaign(campaign_id, campaign)
    if not updated_campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return updated_campaign


class PermissionResponse(BaseModel):
    can_edit: bool
    can_delete: bool
    is_owner: bool


@router.get("/{campaign_id}/permissions", response_model=PermissionResponse)
async def get_campaign_permissions(
    campaign_id: int,
    current_user: User = Depends(get_viewer_user),
    allocations: list[str] = Depends(get_user_allocations),
    db: Session = Depends(get_db),
) -> PermissionResponse:
    has_allocation = check_allocation_permission(current_user, campaign_id, allocations)
    return PermissionResponse(
        can_edit=has_allocation,
        can_delete=has_allocation,
        is_owner=has_allocation,
    )


@router.post("/{campaign_id}/publish", response_model=PublishResponse)
async def publish_campaign(
    request: Request,
    campaign_id: int,
    publish_request: PublishRequest | None = None,
    current_user: User = Depends(get_edit_user),
    _token: str | None = Depends(get_oauth_token_optional),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
    allocations: list[str] = Depends(get_user_allocations),
    db: Session = Depends(get_db),
) -> PublishResponse:
    publish_request = publish_request or PublishRequest(cascade=True)
    request_id = request.headers.get("X-Request-ID") or request.query_params.get("_request_id", "")
    logger.info(
        "campaign_publish_start extra=%s",
        {
            "request_id": request_id,
            "campaign_id": campaign_id,
            "username": getattr(current_user, "username", None),
            "cascade": publish_request.cascade,
            "force": publish_request.force,
            "patch_existing_ckan_dataset": publish_request.patch_existing_ckan_dataset,
            "has_tapis_token": bool(tapis_token),
        },
    )

    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")

    campaign_service = CampaignService(CampaignRepository(db))
    campaign = campaign_service.get_campaign_with_summary(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    cascaded_items: list[str] = []
    errors: list[str] = []

    if publish_request.cascade:
        from app.api.v1.routes.campaigns.campaign_stations import publish_station

        station_repo = StationRepository(db)
        stations = station_repo.get_stations_by_campaign_id(campaign_id, page=1, limit=1000)

        for station in stations:
            try:
                logger.info(
                    "campaign_publish_station_start extra=%s",
                    {
                        "request_id": request_id,
                        "campaign_id": campaign_id,
                        "station_id": station.stationid,
                    },
                )
                result = await publish_station(
                    request=request,
                    campaign_id=campaign_id,
                    station_id=station.stationid,
                    publish_request=PublishRequest(
                        cascade=publish_request.cascade,
                        force=publish_request.force,
                        organization=publish_request.organization,
                        patch_existing_ckan_dataset=publish_request.patch_existing_ckan_dataset,
                    ),
                    current_user=current_user,
                    _token=_token,
                    tapis_token=tapis_token,
                    allocations=allocations,
                    db=db,
                )
                if result.success:
                    cascaded_items.append(f"station:{station.stationid}")
                    if result.cascaded_items:
                        cascaded_items.extend(
                            [f"station:{station.stationid}:{item}" for item in result.cascaded_items]
                        )
                else:
                    station_errors = result.errors or [result.message]
                    errors.extend(f"station {station.stationid}: {error}" for error in station_errors)
                logger.info(
                    "campaign_publish_station_result extra=%s",
                    {
                        "request_id": request_id,
                        "campaign_id": campaign_id,
                        "station_id": station.stationid,
                        "success": result.success,
                        "errors": result.errors,
                        "cascaded_items": result.cascaded_items,
                    },
                )
            except HTTPException as exc:
                error_detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                errors.append(f"station {station.stationid}: {error_detail}")
                logger.warning(
                    "campaign_publish_station_error extra=%s",
                    {
                        "request_id": request_id,
                        "campaign_id": campaign_id,
                        "station_id": station.stationid,
                        "error": error_detail,
                    },
                )

    published_at = datetime.utcnow()
    success = len(errors) == 0
    response = PublishResponse(
        success=success,
        message="Campaign marked as published" if success else "Campaign published with some errors",
        published_count=1 + len(cascaded_items),
        errors=errors,
        id=campaign_id,
        type="campaign",
        is_published=True,
        published_at=published_at,
        cascaded_items=cascaded_items,
        error_code="CKAN_PUBLISH_PARTIAL_FAILURE" if errors else None,
        error_title="CKAN publish failed for one or more stations" if errors else None,
        error_detail=errors[0] if errors else None,
    )
    logger.info(
        "campaign_publish_complete extra=%s",
        {
            "request_id": request_id,
            "campaign_id": campaign_id,
            "success": response.success,
            "errors": response.errors,
            "published_count": response.published_count,
            "cascaded_items": response.cascaded_items,
        },
    )
    return response


@router.post("/{campaign_id}/unpublish", response_model=PublishResponse)
async def unpublish_campaign(
    request: Request,
    campaign_id: int,
    publish_request: PublishRequest | None = None,
    current_user: User = Depends(get_edit_user),
    allocations: list[str] = Depends(get_user_allocations),
    _token: str | None = Depends(get_oauth_token_optional),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
    db: Session = Depends(get_db),
) -> PublishResponse:
    publish_request = publish_request or PublishRequest(cascade=True)
    request_id = request.headers.get("X-Request-ID") or request.query_params.get("_request_id", "")
    logger.info(
        "campaign_unpublish_start extra=%s",
        {
            "request_id": request_id,
            "campaign_id": campaign_id,
            "username": getattr(current_user, "username", None),
            "cascade": publish_request.cascade,
            "has_tapis_token": bool(tapis_token),
        },
    )

    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")

    campaign_service = CampaignService(CampaignRepository(db))
    campaign = campaign_service.get_campaign_with_summary(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    cascaded_items: list[str] = []
    errors: list[str] = []

    if publish_request.cascade:
        from app.api.v1.routes.campaigns.campaign_stations import unpublish_station

        station_repo = StationRepository(db)
        stations = station_repo.get_stations_by_campaign_id(campaign_id, page=1, limit=1000)

        for station in stations:
            try:
                result = await unpublish_station(
                    request=request,
                    campaign_id=campaign_id,
                    station_id=station.stationid,
                    allocations=allocations,
                    current_user=current_user,
                    _token=_token,
                    tapis_token=tapis_token,
                    db=db,
                )
                cascaded_items.append(f"station:{station.stationid}")
                if result.cascaded_items:
                    cascaded_items.extend(
                        [f"station:{station.stationid}:{item}" for item in result.cascaded_items]
                    )
                logger.info(
                    "campaign_unpublish_station_result extra=%s",
                    {
                        "request_id": request_id,
                        "campaign_id": campaign_id,
                        "station_id": station.stationid,
                        "success": result.success,
                        "errors": result.errors,
                    },
                )
            except HTTPException as exc:
                error_detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                errors.append(f"station {station.stationid}: {error_detail}")
                logger.warning(
                    "campaign_unpublish_station_error extra=%s",
                    {
                        "request_id": request_id,
                        "campaign_id": campaign_id,
                        "station_id": station.stationid,
                        "error": error_detail,
                    },
                )

    success = len(errors) == 0
    response = PublishResponse(
        success=success,
        message="Campaign marked as private" if success else "Campaign private with some errors",
        published_count=0,
        errors=errors,
        id=campaign_id,
        type="campaign",
        is_published=False,
        published_at=None,
        cascaded_items=cascaded_items,
    )
    logger.info(
        "campaign_unpublish_complete extra=%s",
        {
            "request_id": request_id,
            "campaign_id": campaign_id,
            "success": response.success,
            "errors": response.errors,
            "cascaded_items": response.cascaded_items,
        },
    )
    return response
