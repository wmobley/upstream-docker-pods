import json
import logging
from datetime import datetime
from app.api.v1.schemas.sensor import SensorItem
from app.api.v1.schemas.station import GetStationResponse, StationItemWithSummary, StationCreate, StationCreateResponse, StationUpdate, StationType
from app.db.repositories.station_repository import StationRepository

logger = logging.getLogger(__name__)


def _isoformat_or_none(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


class StationService:
    def __init__(self, station_repository: StationRepository):
        self.station_repository = station_repository

    def create_station(self, station: StationCreate, campaign_id: int) -> StationCreateResponse:
        return StationCreateResponse(id=self.station_repository.create_station(station, campaign_id).stationid)

    def update_station(self, station_id: int, station: StationUpdate) -> StationCreateResponse | None:
        response = self.station_repository.update_station(station_id, station)
        if not response:
            return None
        return StationCreateResponse(
            id=response.campaignid,
        )
    def partial_update_station(self, station_id: int, station: StationUpdate) -> StationCreateResponse | None:
        response = self.station_repository.update_station(station_id, station, partial=True)
        if not response:
            return None
        return StationCreateResponse(
            id=response.campaignid,
        )
    def get_stations_with_summary(self, campaign_id: int, page: int = 1, limit: int = 20) -> tuple[list[StationItemWithSummary], int]:
        rows, total_count = self.station_repository.list_stations_and_summary(campaign_id, page, limit)
        stations : list[StationItemWithSummary] = []
        for row in rows:
            sensor_types : list[str | None] = row[2]
            sensor_variables : list[str | None] = row[3]
            geometry = json.loads(row[4]) if row[4] else {}
            station = StationItemWithSummary(
                id=row[0].stationid,
                name=row[0].stationname,
                description=row[0].description,
                station_type=StationType(row[0].station_type) if row[0].station_type else StationType.STATIC,
                timezone=row[0].timezone,
                geometry=geometry,
                sensor_types=[x for x in sensor_types if x is not None],
                sensor_variables=[x for x in sensor_variables if x is not None],
                sensor_count=row[1],
                is_published=bool(getattr(row[0], "published", False)),
                published_at=getattr(row[0], "published_at", None),
                metadata=getattr(row[0], "meta", None),
            )
            stations.append(station)
        return stations, total_count


    def get_station(self, station_id: int) -> GetStationResponse | None:
        row = self.station_repository.get_station(station_id)
        logger.info(
            "station_service_get_station_row extra=%s",
            {
                "station_id": station_id,
                "row_found": row is not None,
                "row_published": bool(getattr(row, "published", False)) if row else None,
                "row_published_at": _isoformat_or_none(getattr(row, "published_at", None) if row else None),
            },
        )
        geometry = {}
        if row:
            geometry_raw = getattr(row, "geometry_geojson", None)
            if geometry_raw:
                try:
                    geometry = json.loads(geometry_raw)
                except Exception:  # pragma: no cover - defensive fallback
                    geometry = {}

        if not row:
            return None
        response = GetStationResponse(
            id=row.stationid,
            name=row.stationname,
            description=row.description,
            contact_name=row.contactname,
            contact_email=row.contactemail,
            active=row.active,
            start_date=row.startdate,
            station_type=StationType(row.station_type) if row.station_type else StationType.STATIC,
            timezone=row.timezone,
            geometry=geometry,
            is_published=bool(getattr(row, "published", False)),
            published_at=getattr(row, "published_at", None),
            metadata=getattr(row, "meta", None),
            sensors=[
                SensorItem(
                    id=sensor.sensorid,
                    alias=sensor.alias,
                    description=sensor.description,
                    postprocess=sensor.postprocess,
                    postprocessscript=sensor.postprocessscript,
                    units=sensor.units,
                    variablename=sensor.variablename,
                    is_published=bool(getattr(sensor, "published", False)),
                    published_at=getattr(sensor, "published_at", None),
                    metadata=getattr(sensor, "meta", None),
                )
                for sensor in row.sensors
            ]
        )
        logger.info(
            "station_service_get_station_response extra=%s",
            {
                "station_id": station_id,
                "response_is_published": response.is_published,
                "response_published_at": response.published_at.isoformat() if response.published_at else None,
            },
        )
        return response
    def delete_station_sensors(self, station_id: int) ->bool:
        return self.station_repository.delete_station_sensors(station_id)

    def delete_station(self, station_id: int) -> bool:
        return self.station_repository.delete_station(station_id)

    def set_publish_state(self, station_id: int, *, published: bool, published_at: datetime | None) -> bool:
        result = self.station_repository.set_publish_state(
            station_id,
            published=published,
            published_at=published_at,
        )
        logger.info(
            "station_service_set_publish_state extra=%s",
            {
                "station_id": station_id,
                "requested_published": published,
                "requested_published_at": _isoformat_or_none(published_at),
                "result_found": result is not None,
                "result_published": bool(getattr(result, "published", False)) if result else None,
                "result_published_at": _isoformat_or_none(getattr(result, "published_at", None) if result else None),
            },
        )
        return result is not None

    def refresh_geometry(self, station_id: int) -> None:
        """Recalculate station geometry based on associated measurements."""
        self.station_repository.refresh_geometry(station_id)
