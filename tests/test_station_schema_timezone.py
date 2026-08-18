"""Schema-level tests for station timezone validation."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.api.v1.schemas.station import StationCreate, StationUpdate


def create_payload(**overrides):
    payload = {
        "name": "Test Station",
        "description": "A station for testing",
        "active": True,
        "start_date": datetime(2024, 1, 1, 12, 0, 0),
        "station_type": "static",
        "timezone": "America/Chicago",
    }
    payload.update(overrides)
    return payload


class TestStationCreateTimezone:
    def test_timezone_is_required(self):
        with pytest.raises(ValidationError):
            StationCreate(**{k: v for k, v in create_payload().items() if k != "timezone"})

    def test_valid_timezone_accepted(self):
        station = StationCreate(**create_payload())
        assert station.timezone == "America/Chicago"

    def test_invalid_timezone_rejected(self):
        with pytest.raises(ValidationError):
            StationCreate(**create_payload(timezone="Not/AZone"))

    def test_utc_alias_accepted(self):
        station = StationCreate(**create_payload(timezone="UTC"))
        assert station.timezone == "UTC"

    def test_negative_offset_zone_accepted(self):
        station = StationCreate(**create_payload(timezone="Etc/GMT+5"))
        assert station.timezone == "Etc/GMT+5"


class TestStationUpdateTimezone:
    def test_timezone_is_optional(self):
        station = StationUpdate(name="Renamed")
        assert station.timezone is None

    def test_invalid_timezone_rejected(self):
        with pytest.raises(ValidationError):
            StationUpdate(name="Renamed", timezone="Mars/Olympus")

    def test_valid_timezone_accepted(self):
        station = StationUpdate(name="Renamed", timezone="Pacific/Auckland")
        assert station.timezone == "Pacific/Auckland"