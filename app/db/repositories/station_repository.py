from datetime import datetime
from typing import List, Optional, Tuple, Union

from sqlalchemy.orm import Session

from sqlalchemy import func
from sqlalchemy.orm import joinedload
from app.api.v1.schemas.station import StationCreate, StationUpdate
from app.db.models.sensor import Sensor
from app.db.models.station import Station


class StationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_station(self, request: StationCreate, campaign_id: int) -> Station:
        db_station = Station(
            stationname=request.name,
            description=request.description,
            contactname=request.contact_name,
            contactemail=request.contact_email,
            active=request.active,
            startdate=request.start_date,
            campaignid=campaign_id,
            station_type=request.station_type.value
        )
        self.db.add(db_station)
        self.db.commit()
        self.db.refresh(db_station)
        return db_station

    def get_station(self, station_id: int) -> Optional[Station]:
        # Query the station with its sensors and convert geometry to GeoJSON
        result = self.db.query(
            Station,
            func.ST_AsGeoJSON(Station.geometry).label('geometry_str')
        ).options(
            joinedload(Station.sensors)
        ).filter(
            Station.stationid == station_id
        ).first()

        if result:
            station, geometry_str = result
            # Create a new Station instance with the GeoJSON geometry
            station_dict = {
                'stationid': station.stationid,
                'campaignid': station.campaignid,
                'stationname': station.stationname,
                'projectid': station.projectid,
                'description': station.description,
                'contactname': station.contactname,
                'contactemail': station.contactemail,
                'active': station.active,
                'startdate': station.startdate,
                'station_type': station.station_type,
                'geometry': geometry_str,
                'sensors': station.sensors
            }
            return Station(**station_dict)
        return None

    def get_stations_by_campaign_id(self, campaign_id: int, page: int = 1, limit: int = 20) -> List[Station]:
        return self.db.query(Station).filter(Station.campaignid == campaign_id).offset((page - 1) * limit).limit(limit).all()

    def list_stations_and_summary(self, campaign_id: int, page: int = 1, limit: int = 20) -> Tuple[List[Tuple[Station, int, List[Optional[str]], List[Optional[str]], Optional[str]]], int]:
        query = self.db.query(Station,
            func.count(Sensor.sensorid.distinct()).label('sensor_count'),
            func.array_agg(func.distinct(Sensor.alias)).label('sensor_types'),
            func.array_agg(func.distinct(Sensor.variablename)).label('sensor_variables'),
            func.ST_AsGeoJSON(Station.geometry).label('geometry')
        ).select_from(Station).outerjoin(Sensor).filter(Station.campaignid == campaign_id).group_by(Station.stationid)

        total_count = query.count()
        return query.offset((page - 1) * limit).limit(limit).all(), total_count

    def get_stations(
        self,
        campaign_id: Optional[int] = None,
        active: Optional[bool] = None,
        start_date: Optional[datetime] = None,
        page: int = 1,
        limit: int = 20,
    ) -> Tuple[List[Station], int]:
        query = self.db.query(Station)
        if campaign_id:
            query = query.filter(Station.campaignid == campaign_id)
        if active is not None:
            query = query.filter(Station.active == active)
        if start_date:
            query = query.filter(Station.startdate >= start_date)

        total_count = query.count()
        return query.offset((page - 1) * limit).limit(limit).all(), total_count

    def delete_station(self, station_id: int) -> bool:
        db_station = self.get_station(station_id)
        if db_station:
            self.db.delete(db_station)
            self.db.commit()
            return True
        return False
    
    def delete_station_sensors(self, station_id: int) -> bool:
        self.db.query(Sensor).filter(Sensor.stationid == station_id).delete()
        self.db.commit()
        return True

    def update_station(self, station_id: int, request:  StationUpdate, partial: bool = False) -> Optional[Station]:
        
        db_station = self.db.query(Station).filter(Station.stationid == station_id).first()
        
        if not db_station:
            return None
        
        if partial:
            # Get only the fields that were explicitly set in the request
            update_data = request.model_dump(exclude_unset=True)
            field_mapping = {
                'name': 'stationname',
                'contact_name': 'contactname',
                'contact_email': 'contactemail',
                'active': 'active',
                'start_date': 'startdate',
                
            }
        
            for field, value in update_data.items():
                db_field = field_mapping.get(field, field)
                setattr(db_station, db_field, value)
        else:
            # Full update (existing logic)
            # Ensure all fields for a full update are provided and not None
            name = request.name
            description = request.description
            contact_name = request.contact_name
            contact_email = request.contact_email
            active = request.active
            start_date = request.start_date
            

            if name is None:
                raise ValueError("Campaign name must be provided for a full update")
            if description is None:
                raise ValueError("Campaign description must be provided for a full update")
            if contact_name is None:
                raise ValueError("Contact name must be provided for a full update")
            if contact_email is None:
                raise ValueError("Contact email must be provided for a full update")
            if active is None:
                raise ValueError("Active must be provided for a full update")
            if start_date is None:
                raise ValueError("Start date must be provided for a full update")
            
            db_station.stationname = name
            db_station.description = description
            db_station.contactname = contact_name
            db_station.contactemail = contact_email 
            db_station.active = active
            db_station.startdate = start_date
            
        self.db.commit()
        self.db.refresh(db_station)
        return db_station