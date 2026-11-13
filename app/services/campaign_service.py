from datetime import datetime, timezone
from collections import defaultdict
import json
from typing import Any
from app.api.v1.schemas.station import SensorSummaryForStations, StationsListResponseItem
from app.db.repositories.campaign_repository import CampaignRepository
from app.services.staleness import is_station_stale
from app.api.v1.schemas.campaign import CampaignsIn, CampaignCreateResponse, GetCampaignResponse, ListCampaignsResponseItem, Location, SummaryGetCampaign, SummaryListCampaigns, CampaignUpdate


def summarize_freshness(
    stations: list[tuple[dict[str, Any] | None, datetime | None]],
    campaign_start: datetime | None,
    campaign_end: datetime | None,
) -> tuple[datetime | None, int]:
    """Newest measurement time and number of stale stations in a campaign.

    ``stations`` holds ``(station_metadata, last_measurement_time)`` pairs.
    """
    times = [t for _, t in stations if t is not None]
    # Mixed naive/aware values would make max() raise; normalise to UTC first.
    aware = [t if t.tzinfo else t.replace(tzinfo=timezone.utc) for t in times]
    stale = sum(
        is_station_stale(t, meta, campaign_start, campaign_end) for meta, t in stations
    )
    return (max(aware) if aware else None), stale


class CampaignService:
    def __init__(self, campaign_repository: CampaignRepository):
        self.campaign_repository = campaign_repository

    def create_campaign(self, campaign: CampaignsIn) -> CampaignCreateResponse:
        response = self.campaign_repository.create_campaign(campaign)
        return CampaignCreateResponse(
            id=response.campaignid,
        )
    def update_campaign(self, campaign_id: int, campaign: CampaignsIn) -> CampaignCreateResponse | None:
        response = self.campaign_repository.update_campaign(campaign_id, campaign)
        if not response:
            return None
        return CampaignCreateResponse(
            id=response.campaignid,
        )
    def partial_update_campaign(self, campaign_id: int, campaign: CampaignUpdate) -> CampaignCreateResponse | None:
        response = self.campaign_repository.update_campaign(campaign_id, campaign, partial=True)
        if not response:
            return None
        return CampaignCreateResponse(
            id=response.campaignid,
        )

    def get_campaigns_with_summary(
        self,
        bbox: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        sensor_variables: list[str] | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[ListCampaignsResponseItem], int]:
        rows, total_count = self.campaign_repository.get_campaigns_and_summary(
            bbox, start_date, end_date, sensor_variables, page, limit
        )
        freshness_by_campaign: dict[int, list[tuple[dict[str, Any] | None, datetime | None]]] = defaultdict(list)
        for campaign_id, _station_id, meta, last_time in self.campaign_repository.get_station_freshness(
            [row[0].campaignid for row in rows]
        ):
            freshness_by_campaign[campaign_id].append((meta, last_time))
        items: list[ListCampaignsResponseItem] = []
        for row in rows:
            last_measurement_time, stale_station_count = summarize_freshness(
                freshness_by_campaign.get(row[0].campaignid, []),
                row[0].startdate,
                row[0].enddate,
            )
            sensor_types : list[str | None] = row[3]
            variable_names : list[str | None] = row[4]
            item = ListCampaignsResponseItem(
                id=row[0].campaignid,
                name=row[0].campaignname,
                description=row[0].description,
                contact_name=row[0].contactname,
                contact_email=row[0].contactemail,
                start_date=row[0].startdate,
                end_date=row[0].enddate,
                allocation=row[0].allocation,
                location=Location(
                    bbox_west=row[0].bbox_west,
                    bbox_east=row[0].bbox_east,
                    bbox_south=row[0].bbox_south,
                    bbox_north=row[0].bbox_north,
                ),
                geometry=json.loads(row[5]) if row[5] else {},
                metadata=row[0].meta if getattr(row[0], "meta", None) is not None else None,
                summary=SummaryListCampaigns(
                    sensor_types=[x for x in sensor_types if x is not None],
                    variable_names=[x for x in variable_names if x is not None],
                    station_count=row[1],
                    last_measurement_time=last_measurement_time,
                    stale_station_count=stale_station_count,
                )
            )
            items.append(item)
        return items, total_count

    def get_campaign_with_summary(self, campaign_id: int) -> GetCampaignResponse | None:
        campaign = self.campaign_repository.get_campaign(campaign_id)
        if not campaign:
            return None
        stations = [StationsListResponseItem(
            id=station.stationid,
            name=station.stationname,
            description=station.description,
            contact_name=station.contactname,
            contact_email=station.contactemail,
            active=station.active,
            start_date=station.startdate,
            timezone=station.timezone,
            is_published=bool(getattr(station, "published", False)),
            published_at=getattr(station, "published_at", None),
            geometry=json.loads(station.geometry) if station.geometry else {},
            metadata=getattr(station, "meta", None),
            sensors=[SensorSummaryForStations(
                id=sensor.sensorid,
                variable_name=sensor.variablename,
                measurement_unit=sensor.units,
            ) for sensor in station.sensors]
        ) for station in campaign.stations]
        last_measurement_time, stale_station_count = summarize_freshness(
            [
                (meta, last_time)
                for _, _, meta, last_time in self.campaign_repository.get_station_freshness(
                    [campaign_id]
                )
            ],
            campaign.startdate,
            campaign.enddate,
        )
        return GetCampaignResponse(
            id=campaign.campaignid,
            name=campaign.campaignname,
            description=campaign.description,
            contact_name=campaign.contactname,
            contact_email=campaign.contactemail,
            start_date=campaign.startdate,
            end_date=campaign.enddate,
            allocation=campaign.allocation,
            location=Location(
                bbox_west=campaign.bbox_west,
                bbox_east=campaign.bbox_east,
                bbox_south=campaign.bbox_south,
                bbox_north=campaign.bbox_north,
            ),
            geometry=json.loads(campaign.geometry) if campaign.geometry else {},  # type: ignore[arg-type]
            stations=stations,
            summary=SummaryGetCampaign(
                station_count=self.campaign_repository.count_stations(campaign_id),
                sensor_count=self.campaign_repository.count_sensors(campaign_id),
                sensor_types=self.campaign_repository.get_sensor_types(campaign_id),
                sensor_variables=self.campaign_repository.get_sensor_variables(campaign_id),
                last_measurement_time=last_measurement_time,
                stale_station_count=stale_station_count,
            ),
            metadata=campaign.meta if getattr(campaign, "meta", None) is not None else None,
        )

    def delete_campaign_station(self, campaign_id: int) ->bool:
            return self.campaign_repository.delete_campaign_stations(campaign_id)

    def delete_campaign(self, campaign_id: int) ->bool:
            return self.campaign_repository.delete_campaign(campaign_id)
