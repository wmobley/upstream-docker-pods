import json
from app.api.v1.schemas.sensor import SensorItem
from app.api.v1.schemas.station import GetStationResponse,  StationItemWithSummary, StationCreate, StationCreateResponse, StationUpdate
from app.db.repositories.station_repository import StationRepository


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
    def get_stations_with_summary(self, campaign_id: int, page: int = 1, limit: int = 20, published_only: bool = False) -> tuple[list[StationItemWithSummary], int]:
        rows, total_count = self.station_repository.list_stations_and_summary(campaign_id, page, limit, published_only)
        stations : list[StationItemWithSummary] = []
        for row in rows:
            sensor_types : list[str | None] = row[2]
            sensor_variables : list[str | None] = row[3]
            geometry = json.loads(row[4]) if row[4] else {}
            station = StationItemWithSummary(
                id=row[0].stationid,
                name=row[0].stationname,
                description=row[0].description,
                geometry=geometry,
                sensor_types=[x for x in sensor_types if x is not None],
                sensor_variables=[x for x in sensor_variables if x is not None],
                sensor_count=row[1]
            )
            # include publishing state from DB
            try:
                station.is_published = getattr(row[0], 'is_published', False)
                station.published_at = getattr(row[0], 'published_at', None)
            except Exception:
                pass
            stations.append(station)
        return stations, total_count


    def get_station(self, station_id: int, published_only: bool = False) -> GetStationResponse | None:
        row = self.station_repository.get_station(station_id, published_only)
        geometry = {}
        if row:
            try:
                geometry = json.loads(row.geometry) # type: ignore[arg-type]
            except Exception as e:
                print(e)


        if not row:
            return None
        return GetStationResponse(
            id=row.stationid,
            name=row.stationname,
            description=row.description,
            contact_name=row.contactname,
            contact_email=row.contactemail,
            active=row.active,
            start_date=row.startdate,
            geometry=geometry,
            sensors=[SensorItem(
                id=sensor.sensorid,
                alias=sensor.alias,
                description=sensor.description,
                postprocess=sensor.postprocess,
                variablename=sensor.variablename,
                # surface sensor publishing state
                is_published=getattr(sensor, 'is_published', False),
                published_at=getattr(sensor, 'published_at', None),
            ) for sensor in row.sensors],
            # surface station publishing state
            is_published=getattr(row, 'is_published', False),
            published_at=getattr(row, 'published_at', None),
        )
    def delete_station_sensors(self, station_id: int) -> bool:
        return self.station_repository.delete_station_sensors(station_id)

    def delete_station(self, station_id: int) -> bool:
        """Delete an individual station by its ID."""
        return self.station_repository.delete_station(station_id)