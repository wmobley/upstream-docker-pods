"""seed_measurement_data

Revision ID: 987aaf2c48d2
Revises: 41b732659e7c
Create Date: 2025-03-19 16:35:39.556710

"""
import os
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import table, column
from datetime import datetime, timedelta
import random
from geoalchemy2.elements import WKTElement
import math
import geoalchemy2

# revision identifiers, used by Alembic.
revision: str = '987aaf2c48d2'
down_revision: Union[str, None] = '41b732659e7c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def is_dev_environment():
    return os.getenv('ENVIRONMENT') == 'development' or os.getenv('ENVIRONMENT') == 'dev'

# Station coordinates (longitude, latitude)
STATION_LOCATIONS = {
    1: (-97.7431, 30.2672),  # Austin Downtown
    2: (-95.3698, 29.7604),  # Houston Medical Center
    3: (-96.7970, 32.7767),  # Dallas North
    4: (-98.4936, 29.4241),  # San Antonio River Walk
    5: (-106.4850, 31.7619), # El Paso Desert
    6: (-97.5000, 30.5000)   # Test Station
}

def generate_realistic_measurement(sensor_type: str, timestamp: datetime, base_value: float) -> float:
    """Generate realistic measurement values with daily and random variations."""
    hour = timestamp.hour
    day_progress = hour / 24.0  # 0 to 1 throughout the day

    if sensor_type == 'temperature':
        # Daily temperature variation: lowest at 5AM, highest at 3PM
        daily_variation = -5 * (((hour - 15) ** 2) / 100)  # Parabolic curve
        return base_value + daily_variation + random.uniform(-1, 1)

    elif sensor_type == 'humidity':
        # Humidity: inverse to temperature, highest at night/early morning
        daily_variation = 20 * (((hour - 15) ** 2) / 100)
        return min(95, max(30, base_value + daily_variation + random.uniform(-5, 5)))

    elif sensor_type == 'wind_speed':
        # Wind speed: typically higher during day
        daily_factor = 1 + abs(day_progress - 0.5)
        return max(0, base_value * daily_factor + random.uniform(-2, 2))

    elif sensor_type == 'wind_direction':
        # Wind direction: random variations around prevailing direction
        return (base_value + random.uniform(-45, 45)) % 360

    elif sensor_type == 'pressure':
        # Pressure: subtle daily variation
        daily_variation = 2 * math.sin(2 * math.pi * day_progress)
        return base_value + daily_variation + random.uniform(-1, 1)

    elif sensor_type == 'precipitation':
        # Precipitation: occasional rain events
        if random.random() < 0.1:  # 10% chance of rain
            return random.uniform(0, 5)
        return 0

    elif sensor_type == 'solar_radiation':
        # Solar radiation: follows sun pattern
        if hour < 6 or hour > 20:  # Night time
            return 0
        sun_factor = math.sin(math.pi * ((hour - 6) / 14))  # Peak at noon
        return max(0, 1000 * sun_factor + random.uniform(-50, 50))

    return base_value + random.uniform(-1, 1)  # Default variation

def upgrade() -> None:
    if not is_dev_environment():
        return
    """Add seed data for measurements."""
    measurements_table = table('measurements',
        column('measurementid', sa.Integer),
        column('sensorid', sa.Integer),
        column('stationid', sa.Integer),
        column('variablename', sa.String),
        column('collectiontime', sa.DateTime),
        column('variabletype', sa.String),
        column('description', sa.String),
        column('measurementvalue', sa.Float),
        column('geometry', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326))
    )

    # Base values for different locations (representing climate differences)
    base_values = {
        # Format: {station_id: {sensor_type: base_value}}
        1: {'temperature': 25, 'humidity': 65, 'wind_speed': 3, 'wind_direction': 180, 'pressure': 1013, 'precipitation': 0, 'solar_radiation': 500},  # Austin
        2: {'temperature': 27, 'humidity': 75, 'wind_speed': 4, 'wind_direction': 150, 'pressure': 1012, 'precipitation': 0, 'solar_radiation': 500},  # Houston
        3: {'temperature': 24, 'humidity': 60, 'wind_speed': 5, 'wind_direction': 200, 'pressure': 1014, 'precipitation': 0, 'solar_radiation': 500},  # Dallas
        4: {'temperature': 26, 'humidity': 70, 'wind_speed': 3, 'wind_direction': 170, 'pressure': 1013, 'precipitation': 0, 'solar_radiation': 500},  # San Antonio
        5: {'temperature': 28, 'humidity': 45, 'wind_speed': 6, 'wind_direction': 220, 'pressure': 1010, 'precipitation': 0, 'solar_radiation': 600},  # El Paso
        6: {'temperature': 25, 'humidity': 65, 'wind_speed': 4, 'wind_direction': 180, 'pressure': 1013, 'precipitation': 0, 'solar_radiation': 500}   # Test Station
    }

    # Generate measurements for the last 24 hours
    measurement_records = []
    measurement_id = 1
    end_time = datetime(2024, 3, 19, 16, 0, 0)  # Current time
    start_time = end_time - timedelta(hours=24)  # Last 24 hours

    # Generate hourly measurements for each station and sensor
    current_time = start_time
    while current_time <= end_time:
        for station_id, base_values_dict in base_values.items():
            # Get station location
            lon, lat = STATION_LOCATIONS[station_id]
            geometry = WKTElement(f'POINT({lon} {lat})', srid=4326)

            # Get sensor IDs for this station
            if station_id <= 5:  # Weather Network stations
                sensor_start_id = (station_id - 1) * 7 + 1
                sensor_ids = range(sensor_start_id, sensor_start_id + 7)
            else:  # Test station
                sensor_ids = [36, 37]  # The two test sensors

            for sensor_id in sensor_ids:
                # Determine sensor type based on ID
                if station_id <= 5:
                    sensor_type = ['temperature', 'humidity', 'wind_speed', 'wind_direction',
                                 'pressure', 'precipitation', 'solar_radiation'][(sensor_id - 1) % 7]
                else:
                    sensor_type = 'temperature' if sensor_id == 36 else 'humidity'

                base_value = base_values_dict[sensor_type]
                value = generate_realistic_measurement(sensor_type, current_time, base_value)

                measurement_records.append({
                    'sensorid': sensor_id,
                    'stationid': station_id,
                    'variablename': sensor_type,
                    'collectiontime': current_time,
                    'variabletype': 'float',
                    'description': f'Hourly {sensor_type} measurement',
                    'measurementvalue': value,
                    'geometry': geometry
                })
                measurement_id += 1

        current_time += timedelta(hours=1)

    # Insert all measurement records
    op.get_bind().execute(
        measurements_table.insert().values(measurement_records)
    )


def downgrade() -> None:
    """Remove seed data."""
    op.get_bind().execute(
        sa.text('DELETE FROM measurements WHERE measurementid <= 925')  # 37 sensors * 25 hours
    )
