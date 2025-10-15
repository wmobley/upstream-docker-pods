from datetime import datetime
from typing import Annotated

from app.services.campaign_service import CampaignService
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.api.dependencies.auth import get_current_user
from app.api.dependencies.pytas import check_allocation_permission
from app.api.v1.schemas.station import (
    GetStationResponse,
    ListStationsResponsePagination,
    StationCreate,
    StationCreateResponse,
    StationUpdate,
)
from app.api.v1.schemas.user import User
from app.db.session import get_db
from app.db.repositories.station_repository import StationRepository
from app.db.repositories.campaign_repository import CampaignRepository
from app.db.repositories.sensor_repository import SensorRepository
from app.db.repositories.measurement_repository import MeasurementRepository
from app.services.station_service import StationService
from app.services.export_service import ExportService

router = APIRouter(prefix="/campaigns/{campaign_id}", tags=["stations"])


@router.post("/stations")
async def create_station(
    station: StationCreate,
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationCreateResponse:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    station_service = StationService(StationRepository(db))
    return station_service.create_station(station, campaign_id)


# Route to retrieve all stations associated with a specific campaign
@router.get("/stations")
async def list_stations(
    campaign_id: int,
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ListStationsResponsePagination:
    if not check_allocation_permission(current_user, campaign_id):
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
    db: Session = Depends(get_db),
) -> GetStationResponse:
    if not check_allocation_permission(current_user, campaign_id):
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
) -> Response:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    campaign_repository = CampaignRepository(db)
    campaign_service = CampaignService(campaign_repository=campaign_repository)
    campaign_service.delete_campaign_station(campaign_id=campaign_id)
    return Response(status_code=204)


@router.put("/stations/{station_id}", response_model=StationCreateResponse)
def update_station(
    station_id: int,
    campaign_id: int,
    station: StationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StationCreateResponse:
    if not check_allocation_permission(current_user, campaign_id):
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
) -> StationCreateResponse:
    if not check_allocation_permission(current_user, campaign_id):
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
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export sensors for a station as CSV with streaming support."""
    if not check_allocation_permission(current_user, campaign_id):
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
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export measurements for a station as CSV with streaming support."""
    if not check_allocation_permission(current_user, campaign_id):
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
