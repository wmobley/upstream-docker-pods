#!/usr/bin/env python3
"""
Seed development data through the public API, mirroring the Alembic seed migrations.

This script creates campaigns, stations, sensors, and hourly measurements for
the last 24 hours using the HTTP endpoints exposed by the FastAPI service.

Example:
    python scripts/seed_api_data.py --base-url http://localhost:8000/api/v1
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Tuple, TypedDict

import requests


DEFAULT_BASE_URL = "http://localhost:8000/api/v1"
DEFAULT_TOKEN = "dev-token"


class CampaignSeed(TypedDict):
    name: str
    description: str
    contact_name: str
    contact_email: str
    start_date: str
    end_date: str
    allocation: str


class StationSeed(TypedDict):
    campaign_name: str
    name: str
    project_id: str
    description: str
    contact_name: str
    contact_email: str
    active: bool
    start_date: str
    station_type: str


class SensorSeed(TypedDict):
    alias: str
    description: str
    variablename: str
    units: str
    postprocess: bool
    postprocessscript: str | None


SEED_CAMPAIGNS: List[CampaignSeed] = [
    {
        "name": "Test Campaign 2024",
        "description": "A test campaign for development purposes",
        "contact_name": "John Doe",
        "contact_email": "john.doe@example.com",
        "start_date": "2024-01-01T00:00:00",
        "end_date": "2024-12-31T23:59:59",
        "allocation": "TEST-123",
    },
    {
        "name": "Weather Station Network",
        "description": "Network of weather stations across Texas",
        "contact_name": "Jane Smith",
        "contact_email": "jane.smith@example.com",
        "start_date": "2024-03-01T00:00:00",
        "end_date": "2025-02-28T23:59:59",
        "allocation": "WEATHER-456",
    },
]

STATION_LOCATIONS: Dict[str, Tuple[float, float]] = {
    "Austin Downtown": (-97.7431, 30.2672),
    "Houston Medical Center": (-95.3698, 29.7604),
    "Dallas North": (-96.7970, 32.7767),
    "San Antonio River Walk": (-98.4936, 29.4241),
    "El Paso Desert": (-106.4850, 31.7619),
    "Test Station Alpha": (-97.5000, 30.5000),
}

WEATHER_SENSORS: List[SensorSeed] = [
    {
        "alias": "TEMP",
        "description": "Air temperature sensor",
        "variablename": "temperature",
        "units": "degC",
        "postprocess": True,
        "postprocessscript": "temperature_qc.py",
    },
    {
        "alias": "HUM",
        "description": "Relative humidity sensor",
        "variablename": "humidity",
        "units": "percent",
        "postprocess": True,
        "postprocessscript": "humidity_qc.py",
    },
    {
        "alias": "WSPD",
        "description": "Wind speed sensor",
        "variablename": "wind_speed",
        "units": "m/s",
        "postprocess": True,
        "postprocessscript": "wind_qc.py",
    },
    {
        "alias": "WDIR",
        "description": "Wind direction sensor",
        "variablename": "wind_direction",
        "units": "degrees",
        "postprocess": True,
        "postprocessscript": "wind_qc.py",
    },
    {
        "alias": "PRES",
        "description": "Barometric pressure sensor",
        "variablename": "pressure",
        "units": "hPa",
        "postprocess": True,
        "postprocessscript": "pressure_qc.py",
    },
    {
        "alias": "RAIN",
        "description": "Precipitation sensor",
        "variablename": "precipitation",
        "units": "mm",
        "postprocess": True,
        "postprocessscript": "precipitation_qc.py",
    },
    {
        "alias": "SRAD",
        "description": "Solar radiation sensor",
        "variablename": "solar_radiation",
        "units": "W/m^2",
        "postprocess": True,
        "postprocessscript": "radiation_qc.py",
    },
]

TEST_STATION_SENSORS: List[SensorSeed] = [
    {
        "alias": "TEST-TEMP",
        "description": "Test temperature sensor",
        "variablename": "temperature",
        "units": "degC",
        "postprocess": False,
        "postprocessscript": None,
    },
    {
        "alias": "TEST-HUM",
        "description": "Test humidity sensor",
        "variablename": "humidity",
        "units": "percent",
        "postprocess": False,
        "postprocessscript": None,
    },
]

BASE_VALUES: Dict[str, Dict[str, float]] = {
    "Austin Downtown": {
        "temperature": 25.0,
        "humidity": 65.0,
        "wind_speed": 3.0,
        "wind_direction": 180.0,
        "pressure": 1013.0,
        "precipitation": 0.0,
        "solar_radiation": 500.0,
    },
    "Houston Medical Center": {
        "temperature": 27.0,
        "humidity": 75.0,
        "wind_speed": 4.0,
        "wind_direction": 150.0,
        "pressure": 1012.0,
        "precipitation": 0.0,
        "solar_radiation": 500.0,
    },
    "Dallas North": {
        "temperature": 24.0,
        "humidity": 60.0,
        "wind_speed": 5.0,
        "wind_direction": 200.0,
        "pressure": 1014.0,
        "precipitation": 0.0,
        "solar_radiation": 500.0,
    },
    "San Antonio River Walk": {
        "temperature": 26.0,
        "humidity": 70.0,
        "wind_speed": 3.0,
        "wind_direction": 170.0,
        "pressure": 1013.0,
        "precipitation": 0.0,
        "solar_radiation": 500.0,
    },
    "El Paso Desert": {
        "temperature": 28.0,
        "humidity": 45.0,
        "wind_speed": 6.0,
        "wind_direction": 220.0,
        "pressure": 1010.0,
        "precipitation": 0.0,
        "solar_radiation": 600.0,
    },
    "Test Station Alpha": {
        "temperature": 25.0,
        "humidity": 65.0,
        "wind_speed": 4.0,
        "wind_direction": 180.0,
        "pressure": 1013.0,
        "precipitation": 0.0,
        "solar_radiation": 500.0,
    },
}

STATION_SEEDS: List[StationSeed] = [
    {
        "campaign_name": "Weather Station Network",
        "name": "Austin Downtown",
        "project_id": "ATX-001",
        "description": "Central Austin weather monitoring station located in downtown area",
        "contact_name": "Jane Smith",
        "contact_email": "jane.smith@example.com",
        "active": True,
        "start_date": "2024-03-01T00:00:00",
        "station_type": "static",
    },
    {
        "campaign_name": "Weather Station Network",
        "name": "Houston Medical Center",
        "project_id": "HOU-001",
        "description": "Weather station in Texas Medical Center monitoring urban climate",
        "contact_name": "Jane Smith",
        "contact_email": "jane.smith@example.com",
        "active": True,
        "start_date": "2024-03-01T00:00:00",
        "station_type": "static",
    },
    {
        "campaign_name": "Weather Station Network",
        "name": "Dallas North",
        "project_id": "DFW-001",
        "description": "North Dallas station monitoring suburban weather patterns",
        "contact_name": "Jane Smith",
        "contact_email": "jane.smith@example.com",
        "active": True,
        "start_date": "2024-03-01T00:00:00",
        "station_type": "static",
    },
    {
        "campaign_name": "Weather Station Network",
        "name": "San Antonio River Walk",
        "project_id": "SAT-001",
        "description": "Downtown San Antonio station monitoring urban microclimate",
        "contact_name": "Jane Smith",
        "contact_email": "jane.smith@example.com",
        "active": True,
        "start_date": "2024-03-01T00:00:00",
        "station_type": "static",
    },
    {
        "campaign_name": "Weather Station Network",
        "name": "El Paso Desert",
        "project_id": "ELP-001",
        "description": "Station monitoring arid climate conditions in West Texas",
        "contact_name": "Jane Smith",
        "contact_email": "jane.smith@example.com",
        "active": True,
        "start_date": "2024-03-01T00:00:00",
        "station_type": "static",
    },
    {
        "campaign_name": "Test Campaign 2024",
        "name": "Test Station Alpha",
        "project_id": "TEST-001",
        "description": "Test station for development and testing purposes",
        "contact_name": "John Doe",
        "contact_email": "john.doe@example.com",
        "active": True,
        "start_date": "2024-01-01T00:00:00",
        "station_type": "static",
    },
]


def log(message: str) -> None:
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[seed-api {now}] {message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed development data via the public API.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("UPSTREAM_API_BASE_URL", DEFAULT_BASE_URL),
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("API_BEARER_TOKEN", DEFAULT_TOKEN),
        help="Bearer token for Authorization header (default: %(default)s)",
    )
    parser.add_argument(
        "--tapis-token",
        default=os.getenv("TAPIS_TOKEN"),
        help="Optional Tapis token to forward via X-TAPIS-TOKEN header.",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Number of hourly measurement points to generate per sensor (default: 24).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the actions without performing HTTP requests.",
    )
    parser.add_argument(
        "--skip-measurements",
        action="store_true",
        help="Create campaigns/stations/sensors but skip measurement uploads.",
    )
    return parser.parse_args()


def ensure_campaign(session: requests.Session, base_url: str, campaign: CampaignSeed, dry_run: bool) -> int:
    existing_id = None
    if not dry_run:
        existing_id = find_campaign_id(session, base_url, campaign["name"])
        if existing_id is not None:
            log(f"Campaign '{campaign['name']}' already exists (id={existing_id}).")
            return existing_id
    if dry_run:
        log(f"[dry-run] Would create campaign '{campaign['name']}'.")
        return -1

    payload = {
        "name": campaign["name"],
        "description": campaign["description"],
        "contact_name": campaign["contact_name"],
        "contact_email": campaign["contact_email"],
        "allocation": campaign["allocation"],
        "start_date": campaign["start_date"],
        "end_date": campaign["end_date"],
    }
    response = session.post(f"{base_url}/campaigns", json=payload, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Failed to create campaign '{campaign['name']}': {response.status_code} {response.text}")
    campaign_data: Dict[str, Any] = response.json()
    campaign_id = int(campaign_data["id"])
    log(f"Created campaign '{campaign['name']}' (id={campaign_id}).")
    return campaign_id


def find_campaign_id(session: requests.Session, base_url: str, name: str) -> int | None:
    response = session.get(f"{base_url}/campaigns", params={"page": 1, "limit": 200}, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Cannot list campaigns: {response.status_code} {response.text}")
    for item in response.json().get("items", []):
        if item.get("name") == name:
            return int(item["id"])
    return None


def ensure_station(
    session: requests.Session,
    base_url: str,
    campaign_id: int,
    campaign_name: str,
    station: StationSeed,
    dry_run: bool,
) -> int:
    existing_id = None
    if not dry_run:
        existing_id = find_station_id(session, base_url, campaign_id, station["name"])
        if existing_id is not None:
            log(f"Station '{station['name']}' already exists in campaign '{campaign_name}' (id={existing_id}).")
            return existing_id
    if dry_run:
        log(f"[dry-run] Would create station '{station['name']}' in campaign '{campaign_name}'.")
        return -1

    payload = {
        "name": station["name"],
        "description": station["description"],
        "contact_name": station["contact_name"],
        "contact_email": station["contact_email"],
        "active": station["active"],
        "start_date": station["start_date"],
        "station_type": station["station_type"],
    }
    response = session.post(f"{base_url}/campaigns/{campaign_id}/stations", json=payload, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to create station '{station['name']}' "
            f"in campaign '{campaign_name}': {response.status_code} {response.text}"
        )
    station_data: Dict[str, Any] = response.json()
    station_id = int(station_data["id"])
    log(f"Created station '{station['name']}' (id={station_id}) in campaign '{campaign_name}'.")
    return station_id


def find_station_id(session: requests.Session, base_url: str, campaign_id: int, name: str) -> int | None:
    response = session.get(f"{base_url}/campaigns/{campaign_id}", timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Cannot fetch campaign {campaign_id}: {response.status_code} {response.text}")
    for station in response.json().get("stations", []):
        if station.get("name") == name:
            return int(station["id"])
    return None


def build_sensors_csv(sensors: Iterable[SensorSeed]) -> bytes:
    buffer = io.StringIO()
    fieldnames = ["alias", "variablename", "description", "units", "postprocess", "postprocessscript"]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for sensor in sensors:
        writer.writerow(
            {
                "alias": sensor["alias"],
                "variablename": sensor["variablename"],
                "description": sensor["description"],
                "units": sensor["units"],
                "postprocess": sensor["postprocess"],
                "postprocessscript": sensor["postprocessscript"] or "",
            }
        )
    return buffer.getvalue().encode("utf-8")


def generate_measurement_value(variable: str, timestamp: datetime, base: float, rng: random.Random) -> float:
    hour = timestamp.hour
    day_fraction = hour / 24.0
    if variable == "temperature":
        daily_variation = -5.0 * ((hour - 15) ** 2) / 100.0
        return base + daily_variation + rng.uniform(-1.0, 1.0)
    if variable == "humidity":
        daily_variation = 20.0 * ((hour - 15) ** 2) / 100.0
        return max(30.0, min(95.0, base + daily_variation + rng.uniform(-5.0, 5.0)))
    if variable == "wind_speed":
        daily_factor = 1.0 + abs(day_fraction - 0.5)
        return max(0.0, base * daily_factor + rng.uniform(-2.0, 2.0))
    if variable == "wind_direction":
        return (base + rng.uniform(-45.0, 45.0)) % 360.0
    if variable == "pressure":
        daily_variation = 2.0 * math.sin(day_fraction * 2.0 * math.pi)
        return base + daily_variation + rng.uniform(-1.0, 1.0)
    if variable == "precipitation":
        return rng.uniform(0.0, 5.0) if rng.random() < 0.1 else 0.0
    if variable == "solar_radiation":
        if hour < 6 or hour > 20:
            return 0.0
        sun_factor = math.sin(math.pi * ((hour - 6) / 14.0))
        return max(0.0, base * sun_factor + rng.uniform(-50.0, 50.0))
    return base + rng.uniform(-1.0, 1.0)


def build_measurements_csv(
    station_name: str,
    sensors: Iterable[SensorSeed],
    lon_lat: Tuple[float, float],
    hours: int,
    rng: random.Random,
) -> bytes:
    buffer = io.StringIO()
    sensors_list = list(sensors)
    fieldnames = ["collectiontime", "Lon_deg", "Lat_deg"] + [str(sensor["alias"]) for sensor in sensors_list]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()

    if station_name not in BASE_VALUES:
        raise KeyError(f"No base values configured for station '{station_name}'.")
    base_values = BASE_VALUES[station_name]
    end_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start_time = end_time - timedelta(hours=hours - 1)
    current = start_time

    while current <= end_time:
        row: Dict[str, str | float] = {
            "collectiontime": current.isoformat(),
            "Lon_deg": f"{lon_lat[0]:.5f}",
            "Lat_deg": f"{lon_lat[1]:.5f}",
        }
        for sensor in sensors_list:
            variable = sensor["variablename"]
            base = base_values.get(variable, 0.0)
            row[str(sensor["alias"])] = round(
                generate_measurement_value(variable, current, base, rng), 3
            )
        writer.writerow(row)
        current += timedelta(hours=1)

    return buffer.getvalue().encode("utf-8")


def build_empty_measurements_csv(
    sensors: Iterable[SensorSeed],
    lon_lat: Tuple[float, float],
) -> bytes:
    buffer = io.StringIO()
    sensors_list = list(sensors)
    fieldnames = ["collectiontime", "Lon_deg", "Lat_deg"] + [str(sensor["alias"]) for sensor in sensors_list]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerow(
        {
            "collectiontime": datetime.now(timezone.utc).isoformat(),
            "Lon_deg": f"{lon_lat[0]:.5f}",
            "Lat_deg": f"{lon_lat[1]:.5f}",
        }
    )
    return buffer.getvalue().encode("utf-8")


def seed_sensors_and_measurements(
    session: requests.Session,
    base_url: str,
    campaign_id: int,
    station_id: int,
    station_name: str,
    hours: int,
    dry_run: bool,
    skip_measurements: bool,
) -> None:
    sensors = TEST_STATION_SENSORS if station_name == "Test Station Alpha" else WEATHER_SENSORS
    sensors_csv = build_sensors_csv(sensors)
    rng = random.Random(1337 + station_id)
    measurements_csv = (
        build_measurements_csv(
            station_name,
            sensors,
            STATION_LOCATIONS[station_name],
            hours,
            rng,
        )
        if not skip_measurements
        else build_empty_measurements_csv(sensors, STATION_LOCATIONS[station_name])
    )

    if dry_run:
        log(f"[dry-run] Would upload {len(sensors)} sensors to station '{station_name}'.")
        if not skip_measurements:
            log(f"[dry-run] Would upload measurements ({len(measurements_csv)} bytes).")
        return

    sensors_file = io.BytesIO(sensors_csv)
    sensors_file.seek(0)
    measurements_file = io.BytesIO(measurements_csv)
    measurements_file.seek(0)
    files = {
        "upload_file_sensors": ("sensors.csv", sensors_file, "text/csv"),
        "upload_file_measurements": ("measurements.csv", measurements_file, "text/csv"),
    }

    url = f"{base_url}/uploadfile_csv/campaign/{campaign_id}/station/{station_id}/sensor"
    response = session.post(url, files=files, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to upload sensors/measurements for station '{station_name}': "
            f"{response.status_code} {response.text}"
        )
    detail: Dict[str, Any] = response.json()
    log(
        f"Uploaded sensors to '{station_name}'. "
        f"Measurements added: {detail.get('Total measurements added to database', 0)}."
    )


def main() -> int:
    args = parse_args()

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {args.token}"})
    if args.tapis_token:
        session.headers["X-TAPIS-TOKEN"] = args.tapis_token

    hours = max(1, args.hours)
    campaign_ids: Dict[str, int] = {}
    for campaign in SEED_CAMPAIGNS:
        campaign_id = ensure_campaign(session, args.base_url, campaign, args.dry_run)
        campaign_ids[campaign["name"]] = campaign_id

    for station in STATION_SEEDS:
        campaign_name = station["campaign_name"]
        campaign_id = campaign_ids[campaign_name]
        if campaign_id == -1:
            log(f"[dry-run] Skipping station '{station['name']}' because campaign '{campaign_name}' is dry-run only.")
            continue
        station_id = ensure_station(
            session,
            args.base_url,
            campaign_id,
            campaign_name,
            station,
            args.dry_run,
        )
        if station_id == -1:
            continue
        seed_sensors_and_measurements(
            session,
            args.base_url,
            campaign_id,
            station_id,
            station["name"],
            hours,
            args.dry_run,
            args.skip_measurements,
        )

    log("Seeding complete.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("Aborted by user.")
        sys.exit(130)
    except requests.exceptions.RequestException as exc:
        log(f"HTTP error: {exc}")
        sys.exit(1)
