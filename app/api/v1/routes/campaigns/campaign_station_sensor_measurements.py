import json
from datetime import datetime
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse

from app.api.dependencies.auth import (
    get_current_user_optional,
    get_edit_user,
    get_tapis_token_header_optional,
)
from app.api.dependencies.ckan import (
    check_allocation_permission,
    get_user_allocations,
    resolve_user_allocations,
)
from app.api.v1.schemas.user import User
from app.api.v1.schemas.measurement import (
    AggregatedMeasurement,
    ListMeasurementsResponsePagination,
    MeasurementCreateResponse,
    MeasurementUpdate,
    MeasurementIn,
)
from app.db.models.sensor import Sensor as SensorModel
from app.db.models.station import Station as StationModel
from app.db.repositories.measurement_repository import MeasurementRepository
from app.db.repositories.sensor_repository import SensorRepository
from app.db.repositories.station_repository import StationRepository
from app.db.session import get_db
from app.services.measurement_service import MeasurementService
from app.services.sensor_service import SensorService

router = APIRouter(
    prefix="/campaigns/{campaign_id}/stations/{station_id}/sensors/{sensor_id}",
    tags=["measurements"],
)


def _fetch_station_and_sensor(
    campaign_id: int,
    station_id: int,
    sensor_id: int,
    station_repository: StationRepository,
    sensor_repository: SensorRepository,
) -> Tuple[StationModel, SensorModel]:
    station = station_repository.get_station(station_id)
    if not station or station.campaignid != campaign_id:
        raise HTTPException(status_code=404, detail="Station not found")

    sensor = sensor_repository.get_sensor_entity(sensor_id, station_id=station_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    return station, sensor


def _ensure_sensor_access(
    campaign_id: int,
    station_id: int,
    sensor_id: int,
    *,
    current_user: User | None,
    tapis_token: str | None,
    station_repository: StationRepository,
    sensor_repository: SensorRepository,
) -> Tuple[StationModel | None, SensorModel | None, bool]:
    station: StationModel | None = None
    sensor: SensorModel | None = None
    is_public = False

    if current_user is not None:
        # Read-only access check: degrade gracefully if CKAN is unreachable so a
        # CKAN outage does not block viewing measurements.
        allocations = resolve_user_allocations(current_user, tapis_token, strict=False)
        allowed = check_allocation_permission(current_user, campaign_id, allocations)
        if not allowed:
            raise HTTPException(status_code=404, detail="Allocation is incorrect")
        try:
            station, sensor = _fetch_station_and_sensor(
                campaign_id, station_id, sensor_id, station_repository, sensor_repository
            )
            is_public = bool(getattr(station, "published", False)) and bool(
                getattr(sensor, "published", False)
            )
        except HTTPException:
            station = None
            sensor = None
        except Exception:  # pragma: no cover - defensive fallback
            station = None
            sensor = None
    else:
        try:
            station, sensor = _fetch_station_and_sensor(
                campaign_id, station_id, sensor_id, station_repository, sensor_repository
            )
        except HTTPException as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            ) from exc
        except Exception as exc:  # pragma: no cover
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            ) from exc

        is_public = bool(getattr(station, "published", False)) and bool(
            getattr(sensor, "published", False)
        )
        if not is_public:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

    return station, sensor, is_public


@router.post("/measurements")
async def create_measurement(measurement: MeasurementIn,
                         station_id: int,
                         sensor_id: int,
                         campaign_id: int,
                         current_user: User = Depends(get_edit_user),
                          allocations: list[str] = Depends(get_user_allocations),
                          db: Session = Depends(get_db)) -> MeasurementCreateResponse:
    if not check_allocation_permission(current_user, campaign_id, allocations):
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
    current_user: User | None = Depends(get_current_user_optional),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
    limit: int = 1000,
    page: int = 1,
    downsample_threshold: int | None = None,
    db: Session = Depends(get_db),
) -> ListMeasurementsResponsePagination:
    station_repository = StationRepository(db)
    sensor_repository = SensorRepository(db)
    _ensure_sensor_access(
        campaign_id,
        station_id,
        sensor_id,
        current_user=current_user,
        tapis_token=tapis_token,
        station_repository=station_repository,
        sensor_repository=sensor_repository,
    )

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
    current_user: User | None = Depends(get_current_user_optional),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
    db: Session = Depends(get_db)
) -> list[AggregatedMeasurement]:
    """Get sensor measurements with confidence intervals for visualization."""
    station_repository = StationRepository(db)
    sensor_repository = SensorRepository(db)
    _ensure_sensor_access(
        campaign_id,
        station_id,
        sensor_id,
        current_user=current_user,
        tapis_token=tapis_token,
        station_repository=station_repository,
        sensor_repository=sensor_repository,
    )

    measurement_repository = MeasurementRepository(db)
    measurement_service = MeasurementService(measurement_repository)
    return measurement_service.get_measurements_with_confidence_intervals(sensor_id=sensor_id, interval=interval, interval_value=interval_value, start_date=start_date, end_date=end_date, min_value=min_value, max_value=max_value)


@router.get("/measurements.geojson")
async def get_sensor_measurements_geojson(
    campaign_id: int,
    station_id: int,
    sensor_id: int,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    min_measurement_value: float | None = None,
    max_measurement_value: float | None = None,
    current_user: User | None = Depends(get_current_user_optional),
    tapis_token: str | None = Depends(get_tapis_token_header_optional),
    limit: int = 1000,
    page: int = 1,
    downsample_threshold: int | None = None,
    db: Session = Depends(get_db),
) -> JSONResponse:
    station_repository = StationRepository(db)
    sensor_repository = SensorRepository(db)
    station, sensor, is_public = _ensure_sensor_access(
        campaign_id,
        station_id,
        sensor_id,
        current_user=current_user,
        tapis_token=tapis_token,
        station_repository=station_repository,
        sensor_repository=sensor_repository,
    )

    measurement_repository = MeasurementRepository(db)
    results, total_count, min_value, max_value, average_value = measurement_repository.list_measurements(
        sensor_id=sensor_id,
        start_date=start_date,
        end_date=end_date,
        min_value=min_measurement_value,
        max_value=max_measurement_value,
        page=page,
        limit=limit,
    )

    features = []
    for measurement, geometry_str in results:
        geometry = json.loads(geometry_str) if geometry_str else None
        feature = {
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "measurement_id": measurement.measurementid,
                "sensor_id": measurement.sensorid,
                "variablename": measurement.variablename,
                "variabletype": measurement.variabletype,
                "description": measurement.description,
                "value": measurement.measurementvalue,
                "collection_time": measurement.collectiontime.isoformat(),
                "is_public": is_public,
            },
        }
        features.append(feature)

    feature_collection = {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "station_id": station_id,
            "station_name": getattr(station, "stationname", None),
            "sensor_id": sensor_id,
            "sensor_alias": getattr(sensor, "alias", None),
            "sensor_variable": getattr(sensor, "variablename", None),
            "total": total_count,
            "page": page,
            "page_size": limit,
            "min_value": min_value,
            "max_value": max_value,
            "average_value": average_value,
            "downsample_threshold": downsample_threshold,
        },
    }

    return JSONResponse(content=feature_collection)

@router.delete("/measurements", status_code=204)
def delete_sensor_measurements(
    campaign_id: int,
    station_id: int,
    sensor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_edit_user),
    allocations: list[str] = Depends(get_user_allocations),
) -> Response:
    if not check_allocation_permission(current_user, campaign_id, allocations):
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
    current_user: User = Depends(get_edit_user),
    allocations: list[str] = Depends(get_user_allocations),
    ) -> MeasurementCreateResponse:
    if not check_allocation_permission(current_user, campaign_id, allocations):
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
    current_user: User = Depends(get_edit_user),
    allocations: list[str] = Depends(get_user_allocations),
) -> MeasurementCreateResponse:
    if not check_allocation_permission(current_user, campaign_id, allocations):
        raise HTTPException(status_code=404, detail="Allocation is incorrect")
    measurement_service = MeasurementService(
                                           measurement_repository=MeasurementRepository(db)
)
    updated_measurement = measurement_service.partial_update_measurement(measurement_id, measurement)
    if not updated_measurement:
        raise HTTPException(status_code=404, detail="Measurement not found")
    return updated_measurement
