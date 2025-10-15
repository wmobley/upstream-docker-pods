"""Service for publishing and unpublishing campaigns, stations, sensors, and measurements."""

from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from app.db.models.measurement import Measurement
from app.db.models.sensor import Sensor
from app.db.repositories.campaign_repository import CampaignRepository
from app.db.repositories.measurement_repository import MeasurementRepository
from app.db.repositories.sensor_repository import SensorRepository
from app.db.repositories.station_repository import StationRepository


class PublishingService:
    """Service for managing publish/unpublish operations."""

    def __init__(self, db: Session):
        self.db = db
        self.campaign_repo = CampaignRepository(db)
        self.station_repo = StationRepository(db)
        self.sensor_repo = SensorRepository(db)
        self.measurement_repo = MeasurementRepository(db)

    # Campaign Publishing
    def publish_campaign(
        self, campaign_id: int, cascade: bool = False, force: bool = False
    ) -> Dict[str, Any]:
        """
        Publish a campaign.

        Args:
            campaign_id: ID of the campaign to publish
            cascade: If True, also publish all stations and sensors in the campaign
            force: If True, republish even if already published

        Returns:
            Dict with success status, message, and count of published items
        """
        campaign = self.campaign_repo.get_campaign(campaign_id)
        if not campaign:
            return {
                "success": False,
                "message": f"Campaign {campaign_id} not found",
                "published_count": 0,
                "errors": [f"Campaign {campaign_id} not found"],
            }

        published_count = 0
        errors: List[str] = []
        cascaded_items: List[str] = []

        # Check if already published
        if hasattr(campaign, "published") and campaign.published and not force:
            return {
                "success": False,
                "message": f"Campaign {campaign_id} is already published. Use force=true to republish.",
                "published_count": 0,
                "errors": ["Campaign already published"],
            }

        # Publish the campaign
        if hasattr(campaign, "published"):
            campaign.published = True
            if hasattr(campaign, "published_at"):
                campaign.published_at = datetime.utcnow()
            self.db.commit()
            published_count += 1

        # Cascade to stations and sensors if requested
        if cascade:
            stations = self.station_repo.get_stations_by_campaign_id(campaign_id)
            for station in stations:
                station_identifier = getattr(station, "id", None) or getattr(
                    station, "stationid", None
                )
                if station_identifier is None:
                    errors.append("Encountered station without identifiable ID during publish cascade.")
                    continue
                try:
                    result = self.publish_station(station_identifier, cascade=True, force=force)
                    published_count += result["published_count"]
                    errors.extend(result.get("errors", []))
                    cascaded_items.extend(result.get("cascaded_items", []))
                    cascaded_items.append(f"station:{station_identifier}")
                except Exception as e:
                    errors.append(f"Error publishing station {station_identifier}: {str(e)}")

        return {
            "success": True,
            "message": f"Campaign {campaign_id} published successfully" + (" with cascading" if cascade else ""),
            "published_count": published_count,
            "errors": errors,
            "id": campaign_id,
            "type": "campaign",
            "is_published": True,
            "published_at": getattr(campaign, "published_at", None),
            "cascaded_items": cascaded_items,
        }

    def unpublish_campaign(self, campaign_id: int) -> Dict[str, Any]:
        """
        Unpublish a campaign.

        Args:
            campaign_id: ID of the campaign to unpublish

        Returns:
            Dict with success status and message
        """
        campaign = self.campaign_repo.get_campaign(campaign_id)
        if not campaign:
            return {
                "success": False,
                "message": f"Campaign {campaign_id} not found",
                "published_count": 0,
                "errors": [f"Campaign {campaign_id} not found"],
            }

        if hasattr(campaign, "published"):
            campaign.published = False
            if hasattr(campaign, "published_at"):
                campaign.published_at = None
            self.db.commit()

        return {
            "success": True,
            "message": f"Campaign {campaign_id} unpublished successfully",
            "published_count": 1,
            "errors": [],
            "id": campaign_id,
            "type": "campaign",
            "is_published": False,
            "published_at": None,
            "cascaded_items": [],
        }

    # Station Publishing
    def publish_station(
        self, station_id: int, cascade: bool = False, force: bool = False
    ) -> Dict[str, Any]:
        """
        Publish a station.

        Args:
            station_id: ID of the station to publish
            cascade: If True, also publish all sensors in the station
            force: If True, republish even if already published

        Returns:
            Dict with success status, message, and count of published items
        """
        station = self.station_repo.get_station(station_id)
        if not station:
            return {
                "success": False,
                "message": f"Station {station_id} not found",
                "published_count": 0,
                "errors": [f"Station {station_id} not found"],
            }

        published_count = 0
        errors: List[str] = []
        cascaded_items: List[str] = []

        # Check if already published
        if hasattr(station, "published") and station.published and not force:
            return {
                "success": False,
                "message": f"Station {station_id} is already published. Use force=true to republish.",
                "published_count": 0,
                "errors": ["Station already published"],
            }

        # Publish the station
        if hasattr(station, "published"):
            station.published = True
            if hasattr(station, "published_at"):
                station.published_at = datetime.utcnow()
            self.db.commit()
            published_count += 1

        # Cascade to sensors if requested
        if cascade:
            sensor_entities = (
                self.db.query(Sensor)
                .filter(Sensor.stationid == station_id)
                .all()
            )
            for sensor in sensor_entities:
                sensor_identifier = sensor.sensorid
                try:
                    result = self.publish_sensor(sensor_identifier, cascade=True, force=force)
                    published_count += result["published_count"]
                    errors.extend(result.get("errors", []))
                    cascaded_items.extend(result.get("cascaded_items", []))
                    cascaded_items.append(f"sensor:{sensor_identifier}")
                except Exception as e:
                    errors.append(f"Error publishing sensor {sensor_identifier}: {str(e)}")

        return {
            "success": True,
            "message": f"Station {station_id} published successfully" + (" with cascading" if cascade else ""),
            "published_count": published_count,
            "errors": errors,
            "id": station_id,
            "type": "station",
            "is_published": True,
            "published_at": getattr(station, "published_at", None),
            "cascaded_items": cascaded_items,
        }

    def unpublish_station(self, station_id: int) -> Dict[str, Any]:
        """
        Unpublish a station.

        Args:
            station_id: ID of the station to unpublish

        Returns:
            Dict with success status and message
        """
        station = self.station_repo.get_station(station_id)
        if not station:
            return {
                "success": False,
                "message": f"Station {station_id} not found",
                "published_count": 0,
                "errors": [f"Station {station_id} not found"],
            }

        if hasattr(station, "published"):
            station.published = False
            if hasattr(station, "published_at"):
                station.published_at = None
            self.db.commit()

        return {
            "success": True,
            "message": f"Station {station_id} unpublished successfully",
            "published_count": 1,
            "errors": [],
            "id": station_id,
            "type": "station",
            "is_published": False,
            "published_at": None,
            "cascaded_items": [],
        }

    # Sensor Publishing
    def publish_sensor(
        self, sensor_id: int, cascade: bool = False, force: bool = False
    ) -> Dict[str, Any]:
        """
        Publish a sensor.

        Args:
            sensor_id: ID of the sensor to publish
            cascade: If True, also publish all measurements for the sensor
            force: If True, republish even if already published

        Returns:
            Dict with success status, message, and count of published items
        """
        sensor = (
            self.db.query(Sensor)
            .filter(Sensor.sensorid == sensor_id)
            .first()
        )
        if not sensor:
            return {
                "success": False,
                "message": f"Sensor {sensor_id} not found",
                "published_count": 0,
                "errors": [f"Sensor {sensor_id} not found"],
            }

        published_count = 0
        errors: List[str] = []
        cascaded_items: List[str] = []

        # Check if already published
        if hasattr(sensor, "published") and sensor.published and not force:
            return {
                "success": False,
                "message": f"Sensor {sensor_id} is already published. Use force=true to republish.",
                "published_count": 0,
                "errors": ["Sensor already published"],
            }

        # Publish the sensor
        if hasattr(sensor, "published"):
            sensor.published = True
            if hasattr(sensor, "published_at"):
                sensor.published_at = datetime.utcnow()
            self.db.commit()
            published_count += 1

        # Cascade to measurements if requested
        if cascade:
            measurements = (
                self.db.query(Measurement)
                .filter(Measurement.sensorid == sensor_id)
                .all()
            )
            for measurement in measurements:
                try:
                    if getattr(measurement, "published", False) and not force:
                        continue
                    measurement.published = True
                    if hasattr(measurement, "published_at"):
                        measurement.published_at = datetime.utcnow()
                    published_count += 1
                    cascaded_items.append(f"measurement:{measurement.measurementid}")
                except Exception as exc:  # pragma: no cover - defensive
                    errors.append(f"Error publishing measurement {measurement.measurementid}: {exc}")
            self.db.commit()

        return {
            "success": True,
            "message": f"Sensor {sensor_id} published successfully" + (" with cascading" if cascade else ""),
            "published_count": published_count,
            "errors": errors,
            "id": sensor_id,
            "type": "sensor",
            "is_published": True,
            "published_at": getattr(sensor, "published_at", None),
            "cascaded_items": cascaded_items,
        }

    def unpublish_sensor(self, sensor_id: int) -> Dict[str, Any]:
        """
        Unpublish a sensor.

        Args:
            sensor_id: ID of the sensor to unpublish

        Returns:
            Dict with success status and message
        """
        sensor = (
            self.db.query(Sensor)
            .filter(Sensor.sensorid == sensor_id)
            .first()
        )
        if not sensor:
            return {
                "success": False,
                "message": f"Sensor {sensor_id} not found",
                "published_count": 0,
                "errors": [f"Sensor {sensor_id} not found"],
            }

        if hasattr(sensor, "published"):
            sensor.published = False
            if hasattr(sensor, "published_at"):
                sensor.published_at = None
            self.db.commit()

        return {
            "success": True,
            "message": f"Sensor {sensor_id} unpublished successfully",
            "published_count": 1,
            "errors": [],
            "id": sensor_id,
            "type": "sensor",
            "is_published": False,
            "published_at": None,
            "cascaded_items": [],
        }

    # Measurement Publishing
    def publish_measurements(
        self, measurement_ids: List[int], force: bool = False
    ) -> Dict[str, Any]:
        """
        Publish multiple measurements.

        Args:
            measurement_ids: List of measurement IDs to publish
            force: If True, republish even if already published

        Returns:
            Dict with success status, message, and count of published items
        """
        published_count = 0
        errors: List[str] = []

        cascaded_items: List[str] = []

        for measurement_id in measurement_ids:
            try:
                measurement = (
                    self.db.query(Measurement)
                    .filter(Measurement.measurementid == measurement_id)
                    .first()
                )
                if not measurement:
                    errors.append(f"Measurement {measurement_id} not found")
                    continue

                if hasattr(measurement, "published"):
                    if not measurement.published or force:
                        measurement.published = True
                        if hasattr(measurement, "published_at"):
                            measurement.published_at = datetime.utcnow()
                        published_count += 1
                        cascaded_items.append(f"measurement:{measurement_id}")
            except Exception as e:
                errors.append(f"Error publishing measurement {measurement_id}: {str(e)}")

        self.db.commit()

        return {
            "success": len(errors) == 0 or published_count > 0,
            "message": f"Published {published_count} measurements",
            "published_count": published_count,
            "errors": errors,
            "id": None,
            "type": "measurement",
            "is_published": True if published_count > 0 else None,
            "published_at": datetime.utcnow() if published_count > 0 else None,
            "cascaded_items": cascaded_items,
        }

    def unpublish_measurements(self, measurement_ids: List[int]) -> Dict[str, Any]:
        """
        Unpublish multiple measurements.

        Args:
            measurement_ids: List of measurement IDs to unpublish

        Returns:
            Dict with success status and message
        """
        unpublished_count = 0
        errors: List[str] = []

        cascaded_items: List[str] = []

        for measurement_id in measurement_ids:
            try:
                measurement = (
                    self.db.query(Measurement)
                    .filter(Measurement.measurementid == measurement_id)
                    .first()
                )
                if not measurement:
                    errors.append(f"Measurement {measurement_id} not found")
                    continue

                if hasattr(measurement, "published"):
                    measurement.published = False
                    if hasattr(measurement, "published_at"):
                        measurement.published_at = None
                    unpublished_count += 1
                    cascaded_items.append(f"measurement:{measurement_id}")
            except Exception as e:
                errors.append(f"Error unpublishing measurement {measurement_id}: {str(e)}")

        self.db.commit()

        return {
            "success": len(errors) == 0 or unpublished_count > 0,
            "message": f"Unpublished {unpublished_count} measurements",
            "published_count": unpublished_count,
            "errors": errors,
            "id": None,
            "type": "measurement",
            "is_published": False if unpublished_count > 0 else None,
            "published_at": None,
            "cascaded_items": cascaded_items,
        }
