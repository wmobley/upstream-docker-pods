import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies.auth import (
    get_current_user,
    get_oauth_token_optional,
    get_tapis_token_header,
    get_tapis_token_header_optional,
)
from app.api.dependencies.pytas import check_allocation_permission, get_user_allocations
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
from app.db.repositories.campaign_repository import CampaignRepository
from app.db.repositories.sensor_repository import SensorRepository
from app.db.repositories.measurement_repository import MeasurementRepository
from app.services.station_service import StationService
from app.services.export_service import ExportService
from app.services.campaign_service import CampaignService
from app.services.ckan_service import CKANError, get_ckan_service, _slugify
from app.core.config import get_settings


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/campaigns/{campaign_id}", tags=["stations"])


@router.post("/stations")
async def create_station(
    station: StationCreate,
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    allocations: list[str] = Depends(get_user_allocations),
    _token: str | None = Depends(get_oauth_token_optional),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
    db: Session = Depends(get_db),
) -> StationCreateResponse:
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    station_service = StationService(StationRepository(db))
    response = station_service.create_station(station, campaign_id)

    settings = get_settings()
    ckan_client = get_ckan_service()
    if ckan_client and settings.CKAN_URL and tapis_token:
        try:
            campaign = CampaignService(CampaignRepository(db)).get_campaign_with_summary(campaign_id)
            station_detail = station_service.get_station(response.id)
            if campaign and station_detail:
                dataset_name = _slugify(f"{campaign.name}-{station_detail.name}")
                notes = station_detail.description or f"Station {station_detail.name} in campaign {campaign.name}"
                owner_org = campaign.allocation or settings.CKAN_ORGANIZATION
                tags = {"upstream", _slugify(campaign.name), _slugify(station_detail.name)}
                extras = [
                    {"key": "campaign_id", "value": str(campaign.id)},
                    {"key": "campaign_name", "value": campaign.name},
                    {"key": "station_id", "value": str(station_detail.id)},
                    {"key": "station_name", "value": station_detail.name},
                ]
                ckan_client.create_or_update_dataset(
                    token=tapis_token,
                    name=dataset_name,
                    title=f"{campaign.name} - {station_detail.name}",
                    owner_org=owner_org,
                    notes=notes,
                    tags=tags,
                    extras=extras,
                    private=True,
                )
        except CKANError as exc:
            logger.warning("Failed to register station %s with CKAN: %s", response.id, exc)
        except Exception:
            logger.exception("Unexpected error while registering station %s with CKAN", response.id)

    return response


# Route to retrieve all stations associated with a specific campaign
@router.get("/stations")
async def list_stations(
    campaign_id: int,
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    allocations: list[str] = Depends(get_user_allocations),
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
    station_id: int,
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    allocations: list[str] = Depends(get_user_allocations),
    db: Session = Depends(get_db),
) -> GetStationResponse:
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    station_service = StationService(StationRepository(db))
    station = station_service.get_station(station_id)
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    return station


@router.delete("/stations", status_code=204)
def delete_sensor(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    allocations: list[str] = Depends(get_user_allocations),
) -> Response:
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    campaign_repository = CampaignRepository(db)
    campaign_service = CampaignService(campaign_repository=campaign_repository)
    campaign_service.delete_campaign_station(campaign_id=campaign_id)
    return Response(status_code=204)


@router.delete("/stations/{station_id}", status_code=204)
def delete_station(
    station_id: int,
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
        dataset_name = _slugify(f"{campaign.name}-{station.name}")
        try:
            ckan_client.delete_dataset(token=tapis_token, name_or_id=dataset_name)
        except CKANError as exc:
            logger.warning("Failed to delete station %s dataset from CKAN: %s", station_id, exc)
        except Exception:
            logger.exception("Unexpected error while deleting station %s dataset from CKAN", station_id)

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
    current_user: User = Depends(get_current_user),
    allocations: list[str] = Depends(get_user_allocations),
) -> StationCreateResponse:
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
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
    current_user: User = Depends(get_current_user),
    allocations: list[str] = Depends(get_user_allocations),
) -> StationCreateResponse:
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    station_service = StationService(StationRepository(db))
    update_station = station_service.partial_update_station(station_id, station)
    if not update_station:
        raise HTTPException(status_code=404, detail="Station not found")
    return update_station


@router.get("/stations/{station_id}/sensors/export")
async def export_sensors_csv(
    campaign_id: int,
    station_id: int,
    current_user: User = Depends(get_current_user),
    allocations: list[str] = Depends(get_user_allocations),
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
    current_user: User = Depends(get_current_user),
    allocations: list[str] = Depends(get_user_allocations),
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
    campaign_id: int,
    station_id: int,
    publish_request: PublishRequest | None = None,
    current_user: User = Depends(get_current_user),
    allocations: list[str] = Depends(get_user_allocations),
    _token: str | None = Depends(get_oauth_token_optional),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
    db: Session = Depends(get_db),
) -> PublishResponse:
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
    ckan_errors: list[str] = []
    if ckan_client and settings.CKAN_URL and tapis_token:
        requested_org = ""
        if publish_request and publish_request.organization:
            requested_org = publish_request.organization.strip()
        owner_org_candidate = (requested_org or campaign.allocation or settings.CKAN_ORGANIZATION or "").strip()
        owner_org_slug: str | None = owner_org_candidate or None

        if owner_org_slug:
            try:
                user_orgs = ckan_client.list_user_organizations(token=tapis_token)
            except CKANError as exc:
                message = f"Failed to verify CKAN organization access: {exc}"
                logger.warning("%s", message)
                ckan_errors.append(message)
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
                else:
                    message = (
                        f"Skipping CKAN publication for station {station.id}: "
                        f"user {current_user.username} is not a member of organization '{owner_org_slug}'."
                    )
                    logger.warning("%s", message)
                    ckan_errors.append(message)
                    owner_org_slug = None
        else:
            message = (
                f"Skipping CKAN publication for station {station.id}: "
                "no CKAN organization is configured for this campaign. "
                "Provide an organization in the publish request to publish to CKAN."
            )
            logger.info("%s", message)
            ckan_errors.append(message)

        try:
            if owner_org_slug:
                dataset_name = _slugify(f"{campaign.name}-{station.name}")
                notes = station.description or f"Station {station.name} in campaign {campaign.name}"
                tags = {"upstream", _slugify(campaign.name), _slugify(station.name)}
                source_url = f"{settings.UI_BASE_URL.rstrip('/')}/campaigns/{campaign.id}/stations/{station.id}"
                extras = [
                    {"key": "campaign_id", "value": str(campaign.id)},
                    {"key": "campaign_name", "value": campaign.name},
                    {"key": "station_id", "value": str(station.id)},
                    {"key": "station_name", "value": station.name},
                    {"key": "source", "value": source_url},
                ]
                dataset = ckan_client.create_or_update_dataset(
                    token=tapis_token,
                    name=dataset_name,
                    title=f"{campaign.name} - {station.name}",
                    owner_org=owner_org_slug,
                    notes=notes,
                    tags=tags,
                    extras=extras,
                    private=False,
                )
                dataset_id = dataset.get("id") or dataset.get("name")
                if dataset_id:
                    ckan_client.ensure_dataset_visibility(token=tapis_token, dataset_id=str(dataset_id), private=False)
                    ui_base = settings.UI_BASE_URL.rstrip("/")
                    api_base = settings.API_BASE_URL.rstrip("/") if settings.API_BASE_URL else None

                    existing_resources_by_name: dict[str, Dict[str, Any]] = {}
                    for resource in dataset.get("resources", []) or []:
                        if isinstance(resource, dict):
                            name = resource.get("name")
                            if isinstance(name, str):
                                existing_resources_by_name[name] = resource

                    def _upsert_resource(name: str, url: str, description: str, format_: str, sensor_identifier: str) -> None:
                        existing = existing_resources_by_name.get(name)
                        resource_id = str(existing.get("id")) if existing and existing.get("id") else None
                        try:
                            resource = ckan_client.ensure_resource(
                                token=tapis_token,
                                dataset_id=str(dataset_id),
                                name=name,
                                url=url,
                                description=description,
                                format_=format_,
                                resource_id=resource_id,
                            )
                            existing_resources_by_name[name] = resource
                        except CKANError as exc:
                            message = (
                                f"Failed to register resource {name} for sensor {sensor_identifier} "
                                f"in CKAN: {exc}"
                            )
                            logger.warning("%s", message)
                            ckan_errors.append(message)
                        except Exception as exc:  # pragma: no cover - defensive
                            message = (
                                f"Unexpected error while registering resource {name} for sensor "
                                f"{sensor_identifier} in CKAN: {exc}"
                            )
                            logger.exception("%s", message)
                            ckan_errors.append(message)

                    sensors = station.sensors or []
                    for sensor in sensors:
                        sensor_label = sensor.alias or sensor.variablename or f"sensor-{sensor.id}"
                        sensor_slug = _slugify(f"{station.name}-{sensor_label}") or f"sensor-{sensor.id}"

                        sensor_ui_name = f"{sensor_slug}-ui"
                        sensor_ui_url = f"{ui_base}/campaigns/{campaign.id}/stations/{station.id}/sensors/{sensor.id}"
                        sensor_ui_description = (
                            f"Interactive upstream view for sensor {sensor_label} at station {station.name}."
                        )
                        _upsert_resource(sensor_ui_name, sensor_ui_url, sensor_ui_description, "HTML", str(sensor.id))

                        if not api_base:
                            continue

                        sensor_api_name = f"{sensor_slug}-measurements"
                        sensor_api_url = (
                            f"{api_base}/api/v1/campaigns/{campaign.id}/stations/"
                            f"{station.id}/sensors/{sensor.id}/measurements"
                        )
                        sensor_api_description = (
                            f"Measurement API endpoint (GeoJSON) for sensor {sensor_label} "
                            f"at station {station.name}."
                        )
                        _upsert_resource(sensor_api_name, sensor_api_url, sensor_api_description, "GeoJSON", str(sensor.id))
        except CKANError as exc:
            message = f"Failed to publish station {station_id} in CKAN: {exc}"
            logger.warning("%s", message)
            ckan_errors.append(message)
        except Exception as exc:
            message = f"Unexpected error while publishing station {station_id} in CKAN: {exc}"
            logger.exception("%s", message)
            ckan_errors.append(message)

    published_at = datetime.now(timezone.utc)
    if not station_service.set_publish_state(
        station_id,
        published=True,
        published_at=published_at,
    ):
        raise HTTPException(status_code=500, detail="Failed to update station publish state")

    return PublishResponse(
        success=True,
        message=f"Station {station.name} marked as published",
        published_count=1,
        errors=ckan_errors,
        id=station_id,
        type="station",
        is_published=True,
        published_at=published_at,
        cascaded_items=[],
    )


@router.post("/stations/{station_id}/unpublish", response_model=PublishResponse)
async def unpublish_station(
    campaign_id: int,
    station_id: int,
    current_user: User = Depends(get_current_user),
    allocations: list[str] = Depends(get_user_allocations),
    _token: str | None = Depends(get_oauth_token_optional),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
    db: Session = Depends(get_db),
) -> PublishResponse:
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
    if ckan_client and settings.CKAN_URL and tapis_token:
        try:
            dataset_name = _slugify(f"{campaign.name}-{station.name}")
            dataset = ckan_client.get_dataset(token=tapis_token, name_or_id=dataset_name)
            dataset_id = dataset.get("id") or dataset_name
            if dataset_id:
                ckan_client.ensure_dataset_visibility(token=tapis_token, dataset_id=str(dataset_id), private=True)
        except CKANError as exc:
            logger.warning("Failed to set CKAN dataset %s private: %s", dataset_name, exc)
        except Exception:
            logger.exception("Unexpected error while unpublishing station %s in CKAN", station_id)

    if not station_service.set_publish_state(
        station_id,
        published=False,
        published_at=None,
    ):
        raise HTTPException(status_code=500, detail="Failed to update station publish state")

    return PublishResponse(
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
