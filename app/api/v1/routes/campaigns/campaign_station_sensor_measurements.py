from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.pytas import check_allocation_permission
from app.api.v1.schemas.user import User
from app.api.v1.schemas.measurement import AggregatedMeasurement, ListMeasurementsResponsePagination, MeasurementCreateResponse, MeasurementUpdate, MeasurementIn
from app.db.repositories.measurement_repository import MeasurementRepository
from app.db.repositories.sensor_repository import SensorRepository
from app.db.session import get_db
from app.services.measurement_service import MeasurementService
from app.services.sensor_service import SensorService

router = APIRouter(
    prefix="/campaigns/{campaign_id}/stations/{station_id}/sensors/{sensor_id}",
    tags=["measurements"],
)


@router.post("/measurements")
async def create_measurement(measurement: MeasurementIn,
                         station_id: int,
                         sensor_id: int,
                          campaign_id: int,
                         current_user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)) -> MeasurementCreateResponse:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    measurement_service = MeasurementService(MeasurementRepository(db))
    return measurement_service.create_measurement(measurement, sensor_id) 



@router.get("/measurements")
async def get_sensor_measurements(
    campaign_id: int,
    station_id: int,
    sensor_id: int,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    min_measurement_value: float | None = None,
    max_measurement_value: float | None = None,
    current_user: User = Depends(get_current_user),
    limit: int = 1000,
    page: int = 1,
    downsample_threshold: int | None = None,
    db: Session = Depends(get_db),
) -> ListMeasurementsResponsePagination:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    measurement_repository = MeasurementRepository(db)
    measurement_service = MeasurementService(measurement_repository)
    return measurement_service.list_measurements(sensor_id=sensor_id, start_date=start_date, end_date=end_date, min_value=min_measurement_value, max_value=max_measurement_value, page=page, limit=limit, downsample_threshold=downsample_threshold)

@router.get("/measurements/confidence-intervals", response_model=list[AggregatedMeasurement])
async def get_measurements_with_confidence_intervals(
    campaign_id: int,
    station_id: int,
    sensor_id: int,
    interval: str = Query("hour", description="Time interval for aggregation (minute, hour, day)"),
    interval_value: int = Query(1, description="Multiple of interval (e.g., 15 for 15-minute intervals)"),
    start_date: datetime | None = Query(None, description="Start date for filtering measurements"),
    end_date: datetime | None = Query(None, description="End date for filtering measurements"),
    min_value: float | None = Query(None, description="Minimum measurement value to include"),
    max_value: float | None = Query(None, description="Maximum measurement value to include"),
    db: Session = Depends(get_db)
) -> list[AggregatedMeasurement]:
    """Get sensor measurements with confidence intervals for visualization."""
    measurement_repository = MeasurementRepository(db)
    measurement_service = MeasurementService(measurement_repository)
    return measurement_service.get_measurements_with_confidence_intervals(sensor_id=sensor_id, interval=interval, interval_value=interval_value, start_date=start_date, end_date=end_date, min_value=min_value, max_value=max_value)

@router.delete("/measurements", status_code=204)
def delete_sensor_measurements(
    campaign_id: int,
    station_id: int,
    sensor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    sensor_repository = SensorRepository(db)
    measurement_repository = MeasurementRepository(db)
    sensor_service = SensorService(sensor_repository=sensor_repository, measurement_repository=measurement_repository)
    sensor_service.delete_sensor_measurements(sensor_id=sensor_id)
    return Response(status_code=204)


@router.put("/measurements/{measurement_id}", response_model=MeasurementCreateResponse)
def update_sensor(
    measurement_id: int,
    station_id: int,
    sensor_id: int,
    campaign_id: int,
    measurement: MeasurementUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    ) -> MeasurementCreateResponse:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    measurement_service = MeasurementService(
                                           measurement_repository=MeasurementRepository(db)
)
    updated_measurement = measurement_service.update_measurement(measurement_id, measurement)
    if not updated_measurement:
        raise HTTPException(status_code=404, detail="Measurement not found")
    return updated_measurement

@router.patch("/measurements/{measurement_id}", response_model=MeasurementCreateResponse)
def partial_update_sensor(
    campaign_id: int,
    station_id: int,
    sensor_id: int,
    measurement_id:  int,
    measurement: MeasurementUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MeasurementCreateResponse:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    measurement_service = MeasurementService(
                                           measurement_repository=MeasurementRepository(db)
)
    updated_measurement = measurement_service.partial_update_measurement(measurement_id, measurement)
    if not updated_measurement:
        raise HTTPException(status_code=404, detail="Measurement not found")
    return updated_measurement