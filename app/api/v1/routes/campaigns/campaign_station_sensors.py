from typing import Optional
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.pytas import check_allocation_permission
from app.api.v1.schemas.sensor import SensorItem, GetSensorResponse, ListSensorsResponsePagination, SensorStatistics, SensorCreateResponse, SensorUpdate, ForceUpdateSensorStatisticsResponse, UpdateSensorStatisticsResponse
from app.api.v1.schemas.user import User
from app.db.session import get_db
from app.db.repositories.sensor_repository import SensorRepository, SortField
from app.db.repositories.station_repository import StationRepository
from app.services.sensor_service import SensorService
from app.services.station_service import StationService
from app.db.repositories.measurement_repository import MeasurementRepository


router = APIRouter(
    prefix="/campaigns/{campaign_id}/stations/{station_id}",
    tags=["sensors"],
)

@router.get("/sensors")
async def list_sensors(
    campaign_id: int,
    station_id: int,
    page: int = 1,
    limit: int = 20,
    variable_name: str | None = Query(None, description="Filter sensors by variable name (partial match)"),
    units: str | None = Query(None, description="Filter sensors by units (exact match)"),
    alias: str | None = Query(None, description="Filter sensors by alias (partial match)"),
    description_contains: str | None = Query(None, description="Filter sensors by text in description (partial match)"),
    postprocess: Optional[bool] = Query(None, description="Filter sensors by postprocess flag"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    sort_by: Optional[SortField] = Query(None, description="Sort sensors by field"),
    sort_order: str = Query("asc", description="Sort order (asc or desc)"),
) -> ListSensorsResponsePagination:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")

    sensor_service = SensorService(
        sensor_repository=SensorRepository(db),
        measurement_repository=MeasurementRepository(db)
    )

    items, total_count = sensor_service.get_sensors_by_station_id(
        station_id=station_id,
        page=page,
        limit=limit,
        variable_name=variable_name,
        units=units,
        alias=alias,
        description_contains=description_contains,
        postprocess=postprocess,
        sort_by=sort_by,
        sort_order=sort_order
    )

    return ListSensorsResponsePagination(
        items=items,
        total=total_count,
        page=page,
        size=limit,
        pages=(total_count + limit - 1) // limit,
    )

@router.get("/sensors/{sensor_id}")
async def get_sensor(
    station_id: int,
    sensor_id: int,
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> GetSensorResponse:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")

    sensor_service = SensorService(
        sensor_repository=SensorRepository(db),
        measurement_repository=MeasurementRepository(db)
    )

    response = sensor_service.get_sensor(sensor_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Sensor not found")
    return response


@router.delete("/sensors", status_code=204)
def delete_sensor(
    campaign_id: int,
    station_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    station_repository = StationRepository(db)
    station_service = StationService(station_repository=station_repository)
    station_service.delete_station_sensors(station_id=station_id)
    return Response(status_code=204)



@router.put("/sensors/{sensor_id}", response_model=SensorCreateResponse)
def update_sensor(
    sensor_id: int,
    station_id: int,
    campaign_id: int,
    sensor: SensorUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    ) -> SensorCreateResponse:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    sensor_service = SensorService(SensorRepository(db),
                                           measurement_repository=MeasurementRepository(db)
)
    updated_station = sensor_service.update_sensor(sensor_id, sensor)
    if not updated_station:
        raise HTTPException(status_code=404, detail="Station not found")
    return updated_station

@router.patch("/sensors/{sensor_id}", response_model=SensorCreateResponse)
def partial_update_sensor(
    campaign_id: int,
    station_id: int,
    sensor_id:  int,
    sensor: SensorUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SensorCreateResponse:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    sensor_service = SensorService(SensorRepository(db),
                                           measurement_repository=MeasurementRepository(db)
)
    update_station = sensor_service.partial_update_sensor(sensor_id, sensor)
    if not update_station:
        raise HTTPException(status_code=404, detail="Station not found")
    return update_station


@router.post("/sensors/statistics", 
             response_model=ForceUpdateSensorStatisticsResponse,
             description="Force update sensor statistics for all sensors in the station")
def force_update_sensor_statistics(
    campaign_id: int,
    station_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ForceUpdateSensorStatisticsResponse:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    
    sensor_service = SensorService(
        sensor_repository=SensorRepository(db),
        measurement_repository=MeasurementRepository(db)
    )
    
    return sensor_service.force_update_station_sensor_statistics(station_id)


@router.post("/sensors/{sensor_id}/statistics", 
             response_model=UpdateSensorStatisticsResponse,
             description="Force update sensor statistics for a single sensor")
def force_update_single_sensor_statistics(
    campaign_id: int,
    station_id: int,
    sensor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UpdateSensorStatisticsResponse:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    
    sensor_service = SensorService(
        sensor_repository=SensorRepository(db),
        measurement_repository=MeasurementRepository(db)
    )
    
    return sensor_service.force_update_single_sensor_statistics(sensor_id)

@router.delete("/sensors/{sensor_id}", status_code=204)
def delete_sensor(
    campaign_id: int,
    station_id: int,
    sensor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    if not check_allocation_permission(current_user, campaign_id):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")

    sensor_service = SensorService(
        sensor_repository=SensorRepository(db),
        measurement_repository=MeasurementRepository(db)
    )

    success = sensor_service.delete_sensor(sensor_id)
    if not success:
        raise HTTPException(status_code=404, detail="Sensor not found")

    return Response(status_code=204)