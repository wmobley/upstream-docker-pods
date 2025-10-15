from datetime import datetime
import json
from typing import Union

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, select, or_
from geoalchemy2.functions import ST_AsGeoJSON

from app.api.v1.schemas.campaign import CampaignsIn, CampaignUpdate
from app.db.models.campaign import Campaign
from app.db.models.station import Station
from app.db.models.sensor import Sensor


class CampaignRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_campaign(self, request: CampaignsIn) -> Campaign:
        db_campaign = Campaign(
            campaignname=request.name,
            description=request.description,
            contactname=request.contact_name,
            contactemail=request.contact_email,
            allocation=request.allocation,
            startdate=request.start_date,
            enddate=request.end_date,
        )
        self.db.add(db_campaign)
        self.db.commit()
        self.db.refresh(db_campaign)
        return db_campaign

    def get_campaign(self, id: int) -> Campaign | None:
        stmt = (
            select(Campaign)
            .options(
                joinedload(Campaign.stations).joinedload(Station.sensors),
            )
            .filter(Campaign.campaignid == id)
        )
        result = self.db.execute(stmt).first()

        if not result:
            return None

        campaign : Campaign = result[0]

        if campaign:
            campaign.geometry = self.db.scalar(select(ST_AsGeoJSON(Campaign.geometry)).filter(Campaign.campaignid == id))
            for station in campaign.stations:
                if station.geometry:
                    # Convert each station's geometry to string
                    station_geometry_stmt = select(ST_AsGeoJSON(Station.geometry)).filter(Station.stationid == station.stationid)
                    station.geometry = self.db.scalar(station_geometry_stmt)

        return campaign

    def get_campaigns_and_summary(
        self,
        allocations: list[str] | None,
        bbox: str | None,
        start_date: datetime | None,
        end_date: datetime | None,
        sensor_variables: list[str] | None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[tuple[Campaign, int, int, list[str | None], list[str | None], str | None]], int]:
        # Base campaign query
        query = self.db.query(
            Campaign,
            func.count(Station.stationid.distinct()).label('station_count'),
            func.count(Sensor.sensorid.distinct()).label('sensor_count'),
            func.array_agg(func.distinct(Sensor.alias)).label('sensor_types'),
            func.array_agg(func.distinct(Sensor.variablename)).label('sensor_variables'),
            ST_AsGeoJSON(Campaign.geometry).label('geometry')
        ).select_from(Campaign).outerjoin(Station).outerjoin(Station.sensors).group_by(Campaign.campaignid)

        # Apply filters
        if allocations:
            query = query.filter(Campaign.allocation.in_(allocations))
        if bbox:
            bbox_north, bbox_east, bbox_south, bbox_west = bbox.split(",")
            query = query.filter(
                func.ST_Intersects(
                    Campaign.geometry,
                    func.ST_MakeEnvelope(
                        float(bbox_west),
                        float(bbox_south),
                        float(bbox_east),
                        float(bbox_north),
                        4326  # SRID for WGS84
                    )
                )
            )
        if start_date:
            query = query.filter(
                or_(
                    Campaign.startdate.is_(None),
                    Campaign.startdate >= start_date
                )
            )
        if end_date:
            query = query.filter(
                or_(
                    Campaign.enddate.is_(None),
                    Campaign.enddate <= end_date
                )
            )
        if sensor_variables:
            query = query.filter(Sensor.variablename.in_(sensor_variables))

        total_count = query.count()

        # Get paginated results
        results = query.offset((page - 1) * limit).limit(limit).all()

        return results, total_count

    def delete_campaign(self, campaign_id: int) -> bool:
        db_campaign = self.get_campaign(campaign_id)
        if db_campaign:
            self.db.delete(db_campaign)
            self.db.commit()
            return True
        return False

    def count_stations(self, campaign_id: int) -> int:
        return self.db.query(Station).filter(Station.campaignid == campaign_id).count()

    def count_sensors(self, campaign_id: int) -> int:
        stations = self.db.query(Station).filter(Station.campaignid == campaign_id).all()
        return sum(len(station.sensors) for station in stations)

    def get_sensor_types(self, campaign_id: int) -> list[str]:
        stations = self.db.query(Station).filter(Station.campaignid == campaign_id).all()
        return list(set(sensor.alias for station in stations for sensor in station.sensors))

    def get_sensor_variables(self, campaign_id: int) -> list[str]:
        stations = self.db.query(Station).filter(Station.campaignid == campaign_id).all()
        return list(set(sensor.variablename for station in stations for sensor in station.sensors))

    def delete_campaign_stations(self, campaign_id: int) -> bool:
        self.db.query(Station).filter(Station.campaignid == campaign_id).delete()
        self.db.commit()
        return True

    def update_campaign(self, campaign_id: int, request: Union[CampaignsIn, CampaignUpdate], partial: bool = False) -> Campaign | None:
        db_campaign = self.db.query(Campaign).filter(Campaign.campaignid == campaign_id).first()
        if not db_campaign:
            return None

        if partial:
            # Get only the fields that were explicitly set in the request
            update_data = request.model_dump(exclude_unset=True)
            field_mapping = {
                'name': 'campaignname',
                'contact_name': 'contactname',
                'contact_email': 'contactemail',
                'start_date': 'startdate',
                'end_date': 'enddate'
            }

            for field, value in update_data.items():
                db_field = field_mapping.get(field, field)
                setattr(db_campaign, db_field, value)
        else:
            # Full update (existing logic)
            # Ensure all fields for a full update are provided and not None
            name = request.name
            description = request.description
            contact_name = request.contact_name
            contact_email = request.contact_email
            allocation = request.allocation
            start_date = request.start_date
            end_date = request.end_date

            if name is None:
                raise ValueError("Campaign name must be provided for a full update")
            if description is None:
                raise ValueError("Campaign description must be provided for a full update")
            if contact_name is None:
                raise ValueError("Contact name must be provided for a full update")
            if contact_email is None:
                raise ValueError("Contact email must be provided for a full update")
            if allocation is None:
                raise ValueError("Allocation must be provided for a full update")
            if start_date is None:
                raise ValueError("Start date must be provided for a full update")
            if end_date is None:
                raise ValueError("End date must be provided for a full update")

            db_campaign.campaignname = name
            db_campaign.description = description
            db_campaign.contactname = contact_name
            db_campaign.contactemail = contact_email
            db_campaign.allocation = allocation
            db_campaign.startdate = start_date
            db_campaign.enddate = end_date

        self.db.commit()
        self.db.refresh(db_campaign)
        return db_campaign