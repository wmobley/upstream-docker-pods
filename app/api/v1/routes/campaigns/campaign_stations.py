import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies.auth import (
    get_viewer_user,
    get_edit_user,
    get_oauth_token_optional,
    get_tapis_token_header,
    get_tapis_token_header_optional,
)
from app.api.dependencies.ckan import (
    check_allocation_permission,
    get_user_allocations,
    get_user_allocations_optional,
    user_has_ckan_organization,
)
from app.api.v1.schemas.station import (
    GetStationResponse,
    ListStationsResponsePagination,
    StationCreate,
    StationCreateResponse,
    StationUpdate,
)
from app.api.v1.schemas.campaign import PublishRequest, PublishResponse
from app.api.v1.schemas.user import User
from app.db.session import get_db
from app.db.repositories.station_repository import StationRepository
from app.db.repositories.metadata_schema_repository import MetadataSchemaRepository
from app.db.repositories.campaign_repository import CampaignRepository
from app.db.repositories.sensor_repository import SensorRepository
from app.db.repositories.measurement_repository import MeasurementRepository
from app.services.station_service import StationService
from app.services.export_service import ExportService
from app.services.campaign_service import CampaignService
from app.services.metadata_schema_service import MetadataSchemaService
from app.services.ckan_service import CKANError, CKANService, get_ckan_service, _slugify
from app.services.ckan_publish import (
    DATASET_HASH_EXTRA_KEY,
    build_station_dataset_identity,
    ensure_station_dataset,
    sync_sensor_resources,
)
from app.core.config import get_settings


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/campaigns/{campaign_id}", tags=["stations"])


def _token_summary(token: str | None) -> dict[str, int | str | None]:
    if not token:
        return {"length": None, "dots": None, "prefix": None, "suffix": None}
    return {
        "length": len(token),
        "dots": token.count("."),
        "prefix": token[:16],
        "suffix": token[-16:],
    }


def _delete_station_dataset(
    *,
    ckan_client: CKANService,
    tapis_token: Optional[str],
    campaign: Any,
    station: Any,
) -> None:
    if not tapis_token:
        logger.info(
            "Skipping CKAN dataset deletion for station %s (campaign %s); no Tapis token provided.",
            getattr(station, "id", "unknown"),
            getattr(campaign, "id", "unknown"),
        )
        return
    settings = get_settings()
    dataset_identity = build_station_dataset_identity(settings=settings, campaign=campaign, station=station)
    dataset_slug = dataset_identity["name"]
    legacy_dataset_slug = _slugify(f"{campaign.name}-{station.name}")
    candidate_ids: List[str] = []
    if dataset_slug:
        candidate_ids.append(dataset_slug)
    if legacy_dataset_slug and legacy_dataset_slug != dataset_slug:
        candidate_ids.append(legacy_dataset_slug)
    matches: List[Dict[str, Any]] = []
    find_fn = getattr(ckan_client, "find_datasets_by_extra", None)
    if callable(find_fn) and tapis_token:
        for key, value in (
            (DATASET_HASH_EXTRA_KEY, dataset_identity["hash"]),
            ("source", dataset_identity["source_url"]),
        ):
            try:
                result = find_fn(token=tapis_token, key=key, value=value)
                if isinstance(result, list):
                    matches.extend(entry for entry in result if isinstance(entry, dict))
            except CKANError as exc:  # pragma: no cover - best effort search
                logger.warning("Failed to search CKAN datasets for station %s by %s: %s", station.id, key, exc)
    for match in matches:
        dataset_id = match.get("id") or match.get("name")
        if dataset_id:
            candidate_ids.append(str(dataset_id))
    seen: set[str] = set()
    for candidate in candidate_ids:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            response = ckan_client.delete_dataset(token=tapis_token, name_or_id=candidate)
            logger.info("Deleted CKAN dataset %s for station %s (response=%s)", candidate, station.id, response)
            return
        except CKANError as exc:
            message = str(exc)
            if "not found" in message.lower():
                logger.info(
                    "CKAN dataset %s for station %s (campaign %s) already absent during delete.",
                    candidate,
                    station.id,
                    campaign.id,
                )
                continue
            logger.error(
                "CKAN error while deleting dataset %s for station %s (campaign %s): %s",
                candidate,
                station.id,
                campaign.id,
                message,
            )
            return
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception(
                "Unexpected error while deleting CKAN dataset %s for station %s: %s",
                candidate,
                station.id,
                exc,
            )
            return
    logger.info("No CKAN dataset found for station %s (campaign %s)", station.id, campaign.id)


@router.post("/stations")
async def create_station(
    station: StationCreate,
    campaign_id: int,
    current_user: User = Depends(get_edit_user),
    allocations: list[str] = Depends(get_user_allocations),
    _token: str | None = Depends(get_oauth_token_optional),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
    db: Session = Depends(get_db),
) -> StationCreateResponse:
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    metadata_service = MetadataSchemaService(MetadataSchemaRepository(db))
    errors = metadata_service.validate_metadata("station", station.metadata)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    station_service = StationService(StationRepository(db))
    response = station_service.create_station(station, campaign_id)

    settings = get_settings()
    ckan_client = get_ckan_service()
    if ckan_client and settings.CKAN_URL and tapis_token:
        try:
            campaign = CampaignService(CampaignRepository(db)).get_campaign_with_summary(campaign_id)
            station_detail = station_service.get_station(response.id)
            if campaign and station_detail:
                owner_org = (campaign.allocation or settings.CKAN_ORGANIZATION or "").strip() or None
                if owner_org:
                    metadata_repo = MetadataSchemaRepository(db)
                    station_schema = metadata_repo.list_schema(scope="station", active_only=True)
                    campaign_schema = metadata_repo.list_schema(scope="campaign", active_only=True)
                    dataset, dataset_id, dataset_errors = ensure_station_dataset(
                        settings=settings,
                        ckan_client=ckan_client,
                        tapis_token=tapis_token,
                        campaign=campaign,
                        station=station_detail,
                        owner_org=owner_org,
                        private=True,
                        station_metadata_schema=station_schema,
                        campaign_metadata_schema=campaign_schema,
                    )
                    if not dataset_id and dataset_errors:
                        logger.warning("CKAN dataset creation reported errors for station %s: %s", response.id, dataset_errors)
        except CKANError as exc:
            logger.warning("Failed to register station %s with CKAN: %s", response.id, exc)
        except Exception as exc:
            logger.exception("Unexpected error while registering station %s with CKAN", response.id)
            raise HTTPException(
                status_code=502,
                detail="Unexpected error while creating CKAN dataset for station.",
            ) from exc

    return response


# Route to retrieve all stations associated with a specific campaign
@router.get("/stations")
async def list_stations(
    campaign_id: int,
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(get_viewer_user),
    allocations: list[str] = Depends(get_user_allocations_optional),
    db: Session = Depends(get_db),
) -> ListStationsResponsePagination:
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    station_service = StationService(StationRepository(db))
    stations, total_count = station_service.get_stations_with_summary(
        campaign_id, page, limit
    )
    return ListStationsResponsePagination(
        items=stations,
        total=total_count,
        page=page,
        size=limit,
        pages=total_count // limit + 1,
    )


# Route to retrieve a specific station
@router.get("/stations/{station_id}")
async def get_station(
    request: Request,
    station_id: int,
    campaign_id: int,
    current_user: User = Depends(get_viewer_user),
    allocations: list[str] = Depends(get_user_allocations_optional),
    db: Session = Depends(get_db),
) -> GetStationResponse:
    request_id = request.headers.get("X-Request-ID") or request.query_params.get("_request_id", "")
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    station_service = StationService(StationRepository(db))
    station = station_service.get_station(station_id)
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    logger.info(
        "station_get_route_response extra=%s",
        {
            "request_id": request_id,
            "campaign_id": campaign_id,
            "station_id": station_id,
            "response_is_published": station.is_published,
            "response_published_at": station.published_at.isoformat() if station.published_at else None,
        },
    )
    return station


@router.delete("/stations", status_code=204)
def delete_sensor(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_edit_user),
    allocations: list[str] = Depends(get_user_allocations),
    tapis_token_optional: str | None = Depends(get_tapis_token_header_optional),
) -> Response:
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    campaign_repository = CampaignRepository(db)
    campaign_service = CampaignService(campaign_repository=campaign_repository)

    # If CKAN integration is configured and a tapis token was provided, attempt
    # to delete any associated CKAN datasets for stations before removing them
    # from the database. We accept an optional tapis token header so callers
    # can provide credentials for CKAN operations.
    settings = get_settings()
    ckan_client = get_ckan_service()
    if ckan_client and settings.CKAN_URL:
        tapis_token = tapis_token_optional
        if not tapis_token:
            logger.info("CKAN integration enabled but no Tapis token provided for bulk station delete; skipping CKAN cleanup.")
        else:
            # Enumerate stations so we can delete datasets per station
            campaign = campaign_service.get_campaign_with_summary(campaign_id)
            if campaign and getattr(campaign, "stations", None):
                for station in campaign.stations:
                    _delete_station_dataset(
                        ckan_client=ckan_client,
                        tapis_token=tapis_token,
                        campaign=campaign,
                        station=station,
                    )

    campaign_service.delete_campaign_station(campaign_id=campaign_id)
    return Response(status_code=204)


@router.delete("/stations/{station_id}", status_code=204)
def delete_station(
    station_id: int,
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_edit_user),
    allocations: list[str] = Depends(get_user_allocations),
    tapis_token: str = Depends(get_tapis_token_header),
) -> Response:
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")

    campaign_service = CampaignService(CampaignRepository(db))
    campaign = campaign_service.get_campaign_with_summary(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    station_service = StationService(StationRepository(db))
    station = station_service.get_station(station_id)
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")

    if not any(item.id == station_id for item in campaign.stations):
        raise HTTPException(status_code=404, detail="Station not found")

    settings = get_settings()
    ckan_client = get_ckan_service()
    if ckan_client and settings.CKAN_URL and tapis_token:
        _delete_station_dataset(
            ckan_client=ckan_client,
            tapis_token=tapis_token,
            campaign=campaign,
            station=station,
        )

    # Remove station sensors before deleting the station to avoid FK issues
    station_service.delete_station_sensors(station_id=station_id)
    success = station_service.delete_station(station_id)
    if not success:
        raise HTTPException(status_code=404, detail="Station not found")

    return Response(status_code=204)


@router.put("/stations/{station_id}", response_model=StationCreateResponse)
def update_station(
    station_id: int,
    campaign_id: int,
    station: StationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_edit_user),
    allocations: list[str] = Depends(get_user_allocations),
) -> StationCreateResponse:
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    metadata_service = MetadataSchemaService(MetadataSchemaRepository(db))
    errors = metadata_service.validate_metadata("station", station.metadata)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    station_service = StationService(StationRepository(db))
    updated_station = station_service.update_station(station_id, station)
    if not updated_station:
        raise HTTPException(status_code=404, detail="Station not found")
    return updated_station


@router.patch("/stations/{station_id}", response_model=StationCreateResponse)
def partial_update_station(
    campaign_id: int,
    station_id: int,
    station: StationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_edit_user),
    allocations: list[str] = Depends(get_user_allocations),
) -> StationCreateResponse:
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    metadata_service = MetadataSchemaService(MetadataSchemaRepository(db))
    errors = metadata_service.validate_metadata("station", station.metadata)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    station_service = StationService(StationRepository(db))
    update_station = station_service.partial_update_station(station_id, station)
    if not update_station:
        raise HTTPException(status_code=404, detail="Station not found")
    return update_station


@router.get("/stations/{station_id}/sensors/export")
async def export_sensors_csv(
    campaign_id: int,
    station_id: int,
    current_user: User = Depends(get_viewer_user),
    allocations: list[str] = Depends(get_user_allocations_optional),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export sensors for a station as CSV with streaming support."""
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=403, detail="Access denied")

    # Check if station exists
    station_service = StationService(StationRepository(db))
    station = station_service.get_station(station_id)
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")

    # Initialize export service
    export_service = ExportService(SensorRepository(db), MeasurementRepository(db))

    return StreamingResponse(
        export_service.export_sensors_csv(station_id),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="sensors-{station_id}.csv"'
        },
    )


@router.get("/stations/{station_id}/measurements/export")
async def export_measurements_csv(
    campaign_id: int,
    station_id: int,
    start_date: Annotated[
        datetime | None, Query(description="Start date filter")
    ] = None,
    end_date: Annotated[datetime | None, Query(description="End date filter")] = None,
    current_user: User = Depends(get_viewer_user),
    allocations: list[str] = Depends(get_user_allocations_optional),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export measurements for a station as CSV with streaming support."""
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=403, detail="Access denied")

    # Check if station exists
    station_service = StationService(StationRepository(db))
    station = station_service.get_station(station_id)
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")

    # Initialize export service
    export_service = ExportService(SensorRepository(db), MeasurementRepository(db))

    return StreamingResponse(
        export_service.export_measurements_csv(station_id, start_date, end_date),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="measurements-{station_id}.csv"'
        },
    )


@router.post("/stations/{station_id}/publish", response_model=PublishResponse)
async def publish_station(
    request: Request,
    campaign_id: int,
    station_id: int,
    publish_request: PublishRequest | None = None,
    current_user: User = Depends(get_edit_user),
    allocations: list[str] = Depends(get_user_allocations),
    _token: str | None = Depends(get_oauth_token_optional),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
    db: Session = Depends(get_db),
) -> PublishResponse:
    publish_request = publish_request or PublishRequest()
    request_id = request.headers.get("X-Request-ID") or request.query_params.get("_request_id", "")
    logger.info(
        "station_publish_start extra=%s",
        {
            "request_id": request_id,
            "campaign_id": campaign_id,
            "station_id": station_id,
            "username": getattr(current_user, "username", None),
            "cascade": publish_request.cascade,
            "force": publish_request.force,
            "organization": publish_request.organization,
            "has_tapis_token": bool(tapis_token),
            "tapis_token": _token_summary(tapis_token),
        },
    )
    raw_x_tapis_token = request.headers.get('X-TAPIS-TOKEN') or request.headers.get('X-Tapis-Token') or request.headers.get('x-tapis-token')
    raw_authorization = request.headers.get('Authorization') or request.headers.get('authorization')
    logger.debug(
        "station_publish_token_debug extra=%s",
        {
            "request_id": request_id,
            "campaign_id": campaign_id,
            "station_id": station_id,
            "current_user": getattr(current_user, "username", None),
            "has_oauth_token": bool(_token),
            "oauth_token": _token_summary(_token),
            "has_tapis_token": bool(tapis_token),
            "tapis_token": _token_summary(tapis_token),
        },
    )
    logger.info(
        "station_publish_request_headers extra=%s",
        {
            "request_id": request_id,
            "raw_x_tapis_token_present": bool(raw_x_tapis_token),
            "raw_x_tapis_token": _token_summary(raw_x_tapis_token),
            "raw_authorization_present": bool(raw_authorization),
            "raw_authorization": _token_summary(
                raw_authorization.split(" ", 1)[1] if raw_authorization and raw_authorization.lower().startswith("bearer ") else raw_authorization
            ),
        },
    )
    logger.info(
        "station_publish_raw_request extra=%s",
        {
            "request_id": request_id,
            "url": str(request.url),
            "method": request.method,
            "content_type": request.headers.get("content-type"),
            "accept": request.headers.get("accept"),
            "x_tapis_token_present": bool(raw_x_tapis_token),
            "authorization_present": bool(raw_authorization),
            "x_tapis_token_summary": _token_summary(raw_x_tapis_token),
            "authorization_summary": _token_summary(
                raw_authorization.split(" ", 1)[1] if raw_authorization and raw_authorization.lower().startswith("bearer ") else raw_authorization
            ),
        },
    )
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")

    station_service = StationService(StationRepository(db))
    station = station_service.get_station(station_id)
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")

    campaign_service = CampaignService(CampaignRepository(db))
    campaign = campaign_service.get_campaign_with_summary(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    settings = get_settings()
    ckan_client = get_ckan_service()
    errors: list[str] = []
    owner_org_slug: str | None = None
    ckan_dataset_attempted = False
    ckan_resource_sync_attempted = False
    ckan_branch = "disabled"
    if ckan_client and settings.CKAN_URL and tapis_token:
        ckan_branch = "configured"
        requested_org = ""
        if publish_request.organization:
            requested_org = publish_request.organization.strip()
        owner_org_candidate = (requested_org or campaign.allocation or settings.CKAN_ORGANIZATION or "").strip()
        owner_org_slug = owner_org_candidate or None

        if owner_org_slug:
            try:
                user_orgs = ckan_client.list_user_organizations(token=tapis_token)
            except CKANError as exc:
                message = f"Failed to verify CKAN organization access: {exc}"
                logger.warning("%s", message)
                errors.append(message)
                ckan_branch = "organization_lookup_failed"
            else:
                normalized_candidate = owner_org_slug.lower()

                def _match_org(org: dict[str, Any]) -> bool:
                    identifiers = {
                        (org.get("id") or "").lower(),
                        (org.get("name") or "").lower(),
                    }
                    display_name = org.get("display_name") or org.get("title")
                    if display_name:
                        identifiers.add(str(display_name).lower())
                    return normalized_candidate in identifiers

                matched_org = next((org for org in user_orgs if _match_org(org)), None)
                if matched_org:
                    owner_org_slug = (matched_org.get("name") or matched_org.get("id") or owner_org_slug).strip()
                    ckan_branch = "organization_resolved"
                else:
                    fallback_member = user_has_ckan_organization(
                        token=tapis_token,
                        username=current_user.username,
                        organization=owner_org_slug,
                    )
                    if fallback_member:
                        logger.warning(
                            "CKAN organization_list_for_user returned no match for %s in %s; "
                            "falling back to organization_show membership verification.",
                            current_user.username,
                            owner_org_slug,
                        )
                        ckan_branch = "organization_resolved_fallback"
                    else:
                        message = (
                            f"Skipping CKAN publication for station {station.id}: "
                            f"user {current_user.username} is not a member of organization '{owner_org_slug}'."
                        )
                        logger.warning("%s", message)
                        errors.append(message)
                        ckan_branch = "organization_membership_mismatch"
                        owner_org_slug = None
        else:
            message = (
                f"Skipping CKAN publication for station {station.id}: "
                "no CKAN organization is configured for this campaign. "
                "Provide an organization in the publish request to publish to CKAN."
            )
            logger.info("%s", message)
            errors.append(message)
            ckan_branch = "organization_missing"

        try:
            if owner_org_slug:
                ckan_dataset_attempted = True
                metadata_repo = MetadataSchemaRepository(db)
                station_schema = metadata_repo.list_schema(scope="station", active_only=True)
                campaign_schema = metadata_repo.list_schema(scope="campaign", active_only=True)
                sensor_schema = metadata_repo.list_schema(scope="sensor", active_only=True)
                dataset, dataset_id, dataset_errors = ensure_station_dataset(
                    settings=settings,
                    ckan_client=ckan_client,
                    tapis_token=tapis_token,
                    campaign=campaign,
                    station=station,
                    owner_org=owner_org_slug,
                    private=False,
                    station_metadata_schema=station_schema,
                    campaign_metadata_schema=campaign_schema,
                )
                errors.extend(dataset_errors)
                if dataset_errors:
                    ckan_branch = "dataset_failed"
                sensors = station.sensors or []
                ckan_resource_sync_attempted = True
                resource_errors = sync_sensor_resources(
                    settings=settings,
                    ckan_client=ckan_client,
                    tapis_token=tapis_token,
                    campaign=campaign,
                    station=station,
                    dataset=dataset,
                    dataset_id=dataset_id,
                    sensors=sensors,
                    sensor_metadata_schema=sensor_schema,
                )
                errors.extend(resource_errors)
                if resource_errors:
                    ckan_branch = "resource_sync_failed"
                elif not dataset_errors:
                    ckan_branch = "ckan_sync_complete"
        except CKANError as exc:
            message = f"Failed to publish station {station_id} in CKAN: {exc}"
            logger.warning("%s", message)
            errors.append(message)
            ckan_branch = "ckan_exception"
        except Exception as exc:
            message = f"Unexpected error while publishing station {station_id} in CKAN: {exc}"
            logger.exception("%s", message)
            errors.append(message)
            ckan_branch = "ckan_unexpected_exception"
    elif ckan_client and settings.CKAN_URL and not tapis_token:
        ckan_branch = "missing_tapis_token"
    elif not ckan_client or not settings.CKAN_URL:
        ckan_branch = "ckan_disabled"

    logger.info(
        "station_publish_ckan_branch extra=%s",
        {
            "request_id": request_id,
            "campaign_id": campaign_id,
            "station_id": station_id,
            "ckan_branch": ckan_branch,
            "resolved_owner_org": owner_org_slug,
            "dataset_attempted": ckan_dataset_attempted,
            "resource_sync_attempted": ckan_resource_sync_attempted,
            "errors": errors,
        },
    )

    if ckan_client and settings.CKAN_URL and tapis_token and errors:
        dataset_identity = build_station_dataset_identity(settings=settings, campaign=campaign, station=station)
        dataset_url = f"{settings.CKAN_URL.rstrip('/')}/dataset/{dataset_identity['name']}"
        response = PublishResponse(
            success=False,
            message=f"Station {station.name} not published due to CKAN errors",
            published_count=0,
            errors=errors,
            id=station_id,
            type="station",
            is_published=False,
            published_at=None,
            cascaded_items=[],
            error_code="CKAN_PUBLISH_FAILED",
            error_title="CKAN publish failed",
            error_detail=errors[0] if errors else None,
            ckan_dataset_name=dataset_identity["name"],
            ckan_dataset_url=dataset_url,
        )
        logger.warning(
            "station_publish_complete extra=%s",
            {
                "request_id": request_id,
                "campaign_id": campaign_id,
                "station_id": station_id,
                "success": response.success,
                "errors": response.errors,
                "ckan_branch": ckan_branch,
            },
        )
        return response

    published_at = datetime.now(timezone.utc)
    if not station_service.set_publish_state(
        station_id,
        published=True,
        published_at=published_at,
    ):
        logger.error(
            "station_publish_db_state_failed extra=%s",
            {
                "request_id": request_id,
                "campaign_id": campaign_id,
                "station_id": station_id,
                "published_at": published_at.isoformat(),
            },
        )
        raise HTTPException(status_code=500, detail="Failed to update station publish state")

    cascaded_items: list[str] = []
    if publish_request and publish_request.cascade:
        sensor_repository = SensorRepository(db)
        cascaded_sensor_ids: list[str] = []
        for chunk in sensor_repository.get_sensors_by_station_chunked(station_id):
            for sensor in chunk:
                if getattr(sensor, "published", False) and not publish_request.force:
                    continue
                updated = sensor_repository.set_publish_state(
                    sensor.sensorid,
                    published=True,
                    published_at=published_at,
                )
                if updated:
                    cascaded_sensor_ids.append(str(sensor.sensorid))
                else:
                    errors.append(
                        f"Failed to update sensor {sensor.sensorid} publish state while cascading station publish."
                    )
        cascaded_items.extend(f"sensor:{sensor_id}" for sensor_id in cascaded_sensor_ids)

    response = PublishResponse(
        success=True,
        message=f"Station {station.name} marked as published",
        published_count=1,
        errors=errors,
        id=station_id,
        type="station",
        is_published=True,
        published_at=published_at,
        cascaded_items=cascaded_items,
    )
    logger.info(
        "station_publish_complete extra=%s",
        {
            "request_id": request_id,
            "campaign_id": campaign_id,
            "station_id": station_id,
            "success": response.success,
            "errors": response.errors,
            "cascaded_items": response.cascaded_items,
            "ckan_branch": ckan_branch,
        },
    )
    return response


@router.post("/stations/{station_id}/unpublish", response_model=PublishResponse)
async def unpublish_station(
    request: Request,
    campaign_id: int,
    station_id: int,
    current_user: User = Depends(get_edit_user),
    allocations: list[str] = Depends(get_user_allocations),
    _token: str | None = Depends(get_oauth_token_optional),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
    db: Session = Depends(get_db),
) -> PublishResponse:
    request_id = request.headers.get("X-Request-ID") or request.query_params.get("_request_id", "")
    logger.info(
        "station_unpublish_start extra=%s",
        {
            "request_id": request_id,
            "campaign_id": campaign_id,
            "station_id": station_id,
            "username": getattr(current_user, "username", None),
            "has_tapis_token": bool(tapis_token),
        },
    )
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")

    station_service = StationService(StationRepository(db))
    station = station_service.get_station(station_id)
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")

    campaign_service = CampaignService(CampaignRepository(db))
    campaign = campaign_service.get_campaign_with_summary(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    settings = get_settings()
    ckan_client = get_ckan_service()
    ckan_branch = "ckan_disabled"
    if ckan_client and settings.CKAN_URL and tapis_token:
        try:
            ckan_branch = "dataset_visibility_private"
            dataset_identity = build_station_dataset_identity(settings=settings, campaign=campaign, station=station)
            dataset_name = dataset_identity["name"]
            try:
                dataset = ckan_client.get_dataset(token=tapis_token, name_or_id=dataset_name)
            except CKANError:
                legacy_dataset_name = _slugify(f"{campaign.name}-{station.name}")
                dataset = ckan_client.get_dataset(token=tapis_token, name_or_id=legacy_dataset_name)
                dataset_name = legacy_dataset_name
            dataset_id = dataset.get("id") or dataset_name
            if dataset_id:
                ckan_client.ensure_dataset_visibility(token=tapis_token, dataset_id=str(dataset_id), private=True)
        except CKANError as exc:
            ckan_branch = "dataset_visibility_failed"
            logger.warning("Failed to set CKAN dataset %s private: %s", dataset_name, exc)
        except Exception:
            ckan_branch = "dataset_visibility_unexpected_error"
            logger.exception("Unexpected error while unpublishing station %s in CKAN", station_id)
    elif ckan_client and settings.CKAN_URL and not tapis_token:
        ckan_branch = "missing_tapis_token"

    if not station_service.set_publish_state(
        station_id,
        published=False,
        published_at=None,
    ):
        logger.error(
            "station_unpublish_db_state_failed extra=%s",
            {
                "request_id": request_id,
                "campaign_id": campaign_id,
                "station_id": station_id,
            },
        )
        raise HTTPException(status_code=500, detail="Failed to update station publish state")

    response = PublishResponse(
        success=True,
        message=f"Station {station.name} unpublished from CKAN",
        published_count=0,
        errors=[],
        id=station_id,
        type="station",
        is_published=False,
        published_at=None,
        cascaded_items=[],
    )
    logger.info(
        "station_unpublish_complete extra=%s",
        {
            "request_id": request_id,
            "campaign_id": campaign_id,
            "station_id": station_id,
            "success": response.success,
            "errors": response.errors,
            "ckan_branch": ckan_branch,
        },
    )
    return response
