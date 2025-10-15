from datetime import datetime
import json
from app.api.v1.schemas.station import SensorSummaryForStations, StationsListResponseItem
from app.db.repositories.campaign_repository import CampaignRepository
from app.api.v1.schemas.campaign import CampaignsIn, CampaignCreateResponse, GetCampaignResponse, ListCampaignsResponseItem, Location, SummaryGetCampaign, SummaryListCampaigns, CampaignUpdate


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
        allocations: list[str] | None = None,
        bbox: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        sensor_variables: list[str] | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[ListCampaignsResponseItem], int]:
        rows, total_count = self.campaign_repository.get_campaigns_and_summary(
            allocations, bbox, start_date, end_date, sensor_variables, page, limit
        )
        items: list[ListCampaignsResponseItem] = []
        for row in rows:
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
                summary=SummaryListCampaigns(
                    sensor_types=[x for x in sensor_types if x is not None],
                    variable_names=[x for x in variable_names if x is not None]
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
            geometry=json.loads(station.geometry) if station.geometry else {},
            sensors=[SensorSummaryForStations(
                id=sensor.sensorid,
                variable_name=sensor.variablename,
                measurement_unit=sensor.units,
            ) for sensor in station.sensors]
        ) for station in campaign.stations]
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
            ),
        )

    def delete_campaign_station(self, campaign_id: int) ->bool:
            return self.campaign_repository.delete_campaign_stations(campaign_id)

    def delete_campaign(self, campaign_id: int) ->bool:
            return self.campaign_repository.delete_campaign(campaign_id)
