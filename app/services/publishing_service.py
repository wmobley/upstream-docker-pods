from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException
import logging

from app.db.models.campaign import Campaign
from app.db.models.station import Station
from app.db.models.sensor import Sensor
from app.db.models.measurement import Measurement


class PublishingService:
    """Service to handle publishing operations with cascading logic."""

    def __init__(self, db: Session):
        self.db = db

    def publish_campaign(self, campaign_id: int, cascade: bool = False, force: bool = False) -> dict:
        """Publish a campaign and optionally cascade to stations, sensors, and measurements."""
        campaign = self.db.query(Campaign).filter(Campaign.campaignid == campaign_id).first()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")

        if campaign.is_published:
            logging.info("publish_campaign: campaign %s already published=%s", campaign_id, campaign.is_published)
            raise HTTPException(status_code=400, detail="Campaign is already published")

        # Publish the campaign
        campaign.is_published = True
        campaign.published_at = datetime.utcnow()
        self.db.commit()
        try:
            # refresh instance from DB to ensure commit visibility
            self.db.refresh(campaign)
        except Exception:
            pass
        logging.info("publish_campaign: committed campaign %s published=%s published_at=%s", campaign_id, getattr(campaign, 'is_published', None), getattr(campaign, 'published_at', None))

        cascaded_items = []

        if cascade:
            # Get all stations in this campaign
            stations = self.db.query(Station).filter(Station.campaignid == campaign_id).all()
            for station in stations:
                if not station.is_published:
                    self._publish_station_internal(station, cascade=True)
                    cascaded_items.append(f"station:{station.stationid}")

        return {
            "id": campaign_id,
            "type": "campaign",
            "is_published": True,
            "published_at": campaign.published_at,
            "cascaded_items": cascaded_items
        }

    def publish_station(self, station_id: int, cascade: bool = False, force: bool = False) -> dict:
        """Publish a station and optionally cascade to sensors and measurements."""
        station = self.db.query(Station).filter(Station.stationid == station_id).first()
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")

        if station.is_published:
            logging.info("publish_station: station %s already published=%s", station_id, station.is_published)
            raise HTTPException(status_code=400, detail="Station is already published")
        # Note: children (stations) are allowed to be published even if their parent
        # campaign is not published. The previous behaviour required the parent
        # campaign to be published unless force=True. That check has been removed
        # so clients can publish stations independently of the campaign.
        return self._publish_station_internal(station, cascade)

    def _publish_station_internal(self, station: Station, cascade: bool = False) -> dict:
        """Internal method to publish a station."""
        logging.info("_publish_station_internal: publishing station %s (before: is_published=%s)", station.stationid, getattr(station, 'is_published', None))
        station.is_published = True
        station.published_at = datetime.utcnow()
        self.db.commit()
        try:
            self.db.refresh(station)
        except Exception:
            pass
        logging.info("_publish_station_internal: committed station %s (after: is_published=%s published_at=%s)", station.stationid, getattr(station, 'is_published', None), getattr(station, 'published_at', None))

        cascaded_items = []

        if cascade:
            # Get all sensors in this station
            sensors = self.db.query(Sensor).filter(Sensor.stationid == station.stationid).all()
            for sensor in sensors:
                if not sensor.is_published:
                    self._publish_sensor_internal(sensor, cascade=True)
                    cascaded_items.append(f"sensor:{sensor.sensorid}")

        return {
            "id": station.stationid,
            "type": "station",
            "is_published": True,
            "published_at": station.published_at,
            "cascaded_items": cascaded_items
        }

    def publish_sensor(self, sensor_id: int, cascade: bool = False, force: bool = False) -> dict:
        """Publish a sensor and optionally cascade to measurements."""
        sensor = self.db.query(Sensor).filter(Sensor.sensorid == sensor_id).first()
        if not sensor:
            raise HTTPException(status_code=404, detail="Sensor not found")

        if sensor.is_published:
            raise HTTPException(status_code=400, detail="Sensor is already published")
        # Children (sensors) may be published even if their parent station is not published.
        # Previous behaviour enforced parent station published unless force=True; that has
        # been removed to allow independent publishing of sensors.
        return self._publish_sensor_internal(sensor, cascade)

    def _publish_sensor_internal(self, sensor: Sensor, cascade: bool = False) -> dict:
        """Internal method to publish a sensor."""
        sensor.is_published = True
        sensor.published_at = datetime.utcnow()
        self.db.commit()
        try:
            self.db.refresh(sensor)
        except Exception:
            pass
        cascaded_items = []

        if cascade:
            # Get all measurements for this sensor
            measurements = self.db.query(Measurement).filter(Measurement.sensorid == sensor.sensorid).all()
            for measurement in measurements:
                if not measurement.is_published:
                    self._publish_measurement_internal(measurement)
                    cascaded_items.append(f"measurement:{measurement.measurementid}")

        return {
            "id": sensor.sensorid,
            "type": "sensor",
            "is_published": True,
            "published_at": sensor.published_at,
            "cascaded_items": cascaded_items
        }

    def publish_measurement(self, measurement_id: int, force: bool = False) -> dict:
        """Publish a measurement."""
        measurement = self.db.query(Measurement).filter(Measurement.measurementid == measurement_id).first()
        if not measurement:
            raise HTTPException(status_code=404, detail="Measurement not found")

        if measurement.is_published:
            raise HTTPException(status_code=400, detail="Measurement is already published")
        # Allow publishing measurements even when parent sensor is not published.
        # The parent-published precondition has been removed to permit independent
        # publishing of measurements.
        return self._publish_measurement_internal(measurement)

    def _publish_measurement_internal(self, measurement: Measurement) -> dict:
        """Internal method to publish a measurement."""
        measurement.is_published = True
        measurement.published_at = datetime.utcnow()
        self.db.commit()
        try:
            self.db.refresh(measurement)
        except Exception:
            pass
        return {
            "id": measurement.measurementid,
            "type": "measurement",
            "is_published": True,
            "published_at": measurement.published_at,
            "cascaded_items": []
        }

    def unpublish_campaign(self, campaign_id: int) -> dict:
        """Unpublish a campaign."""
        campaign = self.db.query(Campaign).filter(Campaign.campaignid == campaign_id).first()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")

        if not campaign.is_published:
            raise HTTPException(status_code=400, detail="Campaign is not published")

        campaign.is_published = False
        campaign.published_at = None
        self.db.commit()

        return {
            "id": campaign_id,
            "type": "campaign",
            "is_published": False,
            "published_at": None,
            "cascaded_items": []
        }

    def unpublish_station(self, station_id: int) -> dict:
        """Unpublish a station."""
        station = self.db.query(Station).filter(Station.stationid == station_id).first()
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")

        if not station.is_published:
            raise HTTPException(status_code=400, detail="Station is not published")

        station.is_published = False
        station.published_at = None
        self.db.commit()

        return {
            "id": station_id,
            "type": "station",
            "is_published": False,
            "published_at": None,
            "cascaded_items": []
        }

    def unpublish_sensor(self, sensor_id: int) -> dict:
        """Unpublish a sensor."""
        sensor = self.db.query(Sensor).filter(Sensor.sensorid == sensor_id).first()
        if not sensor:
            raise HTTPException(status_code=404, detail="Sensor not found")

        if not sensor.is_published:
            raise HTTPException(status_code=400, detail="Sensor is not published")

        sensor.is_published = False
        sensor.published_at = None
        self.db.commit()

        return {
            "id": sensor_id,
            "type": "sensor",
            "is_published": False,
            "published_at": None,
            "cascaded_items": []
        }

    def unpublish_measurement(self, measurement_id: int) -> dict:
        """Unpublish a measurement."""
        measurement = self.db.query(Measurement).filter(Measurement.measurementid == measurement_id).first()
        if not measurement:
            raise HTTPException(status_code=404, detail="Measurement not found")

        if not measurement.is_published:
            raise HTTPException(status_code=400, detail="Measurement is not published")

        measurement.is_published = False
        measurement.published_at = None
        self.db.commit()

        return {
            "id": measurement_id,
            "type": "measurement",
            "is_published": False,
            "published_at": None,
            "cascaded_items": []
        }