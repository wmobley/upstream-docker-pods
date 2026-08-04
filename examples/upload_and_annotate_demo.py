#!/usr/bin/env python3
"""
End-to-end demo: create a test campaign + station, upload the example
sensor/measurement CSVs in examples/data/, and exercise the features
added this session — notes at every scope (campaign, station, sensor,
and a measurement note with its own independent location) plus a
custom metadata-schema field.

Requires the `upstream-sdk` package:
    pip install upstream-sdk

Usage:
    export UPSTREAM_USERNAME=<your-username>
    export UPSTREAM_PASSWORD=<your-password>
    export UPSTREAM_BASE_URL=https://upstreamapi.pods.portals.tapis.io  # optional
    export UPSTREAM_ALLOCATION=<your-tacc-allocation-code>  # required by the API
    python3 examples/upload_and_annotate_demo.py

Credentials may also be passed via --username/--password, or you'll be
prompted interactively if neither env vars nor flags are set.
"""
import argparse
import getpass
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from upstream import UpstreamClient
from upstream.exceptions import UpstreamError
from upstream_api_client.models.campaigns_in import CampaignsIn
from upstream_api_client.models.station_create import StationCreate

EXAMPLES_DIR = Path(__file__).resolve().parent / "data"
SENSORS_CSV = EXAMPLES_DIR / "sensors.csv"
MEASUREMENTS_CSV = EXAMPLES_DIR / "measurements.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default=os.getenv("UPSTREAM_USERNAME"))
    parser.add_argument("--password", default=os.getenv("UPSTREAM_PASSWORD"))
    parser.add_argument("--base-url", default=os.getenv("UPSTREAM_BASE_URL"))
    parser.add_argument(
        "--allocation",
        default=os.getenv("UPSTREAM_ALLOCATION"),
        help="TACC allocation/project code the campaign is charged to (required by the API).",
    )
    parser.add_argument(
        "--campaign-name",
        default=None,
        help="Name for the test campaign (default: timestamped, so repeat runs don't collide).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    username = args.username or input("Upstream username: ")
    password = args.password or getpass.getpass("Upstream password: ")
    allocation = args.allocation or input("TACC allocation/project code: ")

    if not SENSORS_CSV.exists() or not MEASUREMENTS_CSV.exists():
        print(f"Expected example CSVs under {EXAMPLES_DIR}", file=sys.stderr)
        return 1

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    campaign_name = args.campaign_name or f"SDK demo campaign ({timestamp})"

    client = UpstreamClient(
        username=username, password=password, base_url=args.base_url
    )

    try:
        print(f"Creating campaign '{campaign_name}'...")
        campaign = client.campaigns.create(
            CampaignsIn(
                name=campaign_name,
                contact_name=username,
                contact_email="",
                description=(
                    "Created by examples/upload_and_annotate_demo.py to exercise "
                    "the example Beaumont stream gauge dataset plus notes and "
                    "metadata-schema support."
                ),
                allocation=allocation,
            )
        )
        campaign_id = campaign.id
        print(f"  campaign_id={campaign_id}")

        station_name = "Beaumont Stream Gauge (demo)"
        print(f"Creating station '{station_name}'...")
        station = client.stations.create(
            campaign_id,
            StationCreate(
                name=station_name,
                description="Demo station seeded from the Beaumont stream gauge example dataset.",
                contact_name=username,
                contact_email="",
                active=True,
                start_date=timestamp,
            ),
        )
        station_id = station.id
        print(f"  station_id={station_id}")

        print(f"Uploading {SENSORS_CSV.name} + {MEASUREMENTS_CSV.name}...")
        upload_result = client.sensors.upload_csv_files(
            campaign_id=campaign_id,
            station_id=station_id,
            sensors_file=str(SENSORS_CSV),
            measurements_file=str(MEASUREMENTS_CSV),
        )
        print(f"  upload result: {upload_result}")

        print("Looking up an uploaded sensor and measurement to annotate...")
        sensors_page = client.sensors.list(campaign_id, station_id, limit=1)
        if not sensors_page.items:
            print("No sensors came back from the upload — skipping sensor/measurement notes.")
            sensor_id = None
            measurement = None
        else:
            sensor_id = sensors_page.items[0].id
            print(f"  sensor_id={sensor_id} (alias={sensors_page.items[0].alias})")
            measurements_page = client.measurements.list(
                campaign_id, station_id, sensor_id, limit=1
            )
            measurement = measurements_page.items[0] if measurements_page.items else None
            if measurement:
                print(f"  measurement_id={measurement.id}")

        print("\nAdding notes at every scope...")

        campaign_note = client.notes.create_campaign_note(
            campaign_id, f"Demo campaign created by upload_and_annotate_demo.py at {timestamp}."
        )
        print(f"  campaign note id={campaign_note.get('id')}")

        station_note = client.notes.create_station_note(
            campaign_id, station_id, "Station seeded from the Beaumont stream gauge example dataset."
        )
        print(f"  station note id={station_note.get('id')}")

        if sensor_id is not None:
            sensor_note = client.notes.create_sensor_note(
                campaign_id, station_id, sensor_id, "First sensor from the uploaded CSV."
            )
            print(f"  sensor note id={sensor_note.get('id')}")

        if measurement is not None:
            # Independent location, separate from the measurement's own geometry —
            # demonstrates the location feature added alongside measurement notes.
            lon, lat = measurement.geometry.coordinates.actual_instance[:2]
            location_wkt = f"POINT({lon} {lat})"
            measurement_note = client.notes.create_measurement_note(
                campaign_id,
                station_id,
                sensor_id,
                measurement.id,
                "First measurement from the uploaded CSV — note carries its own location.",
                location=location_wkt,
            )
            print(f"  measurement note id={measurement_note.get('id')} location={location_wkt}")

        print("\nListing note-location pins (campaign and station scope)...")
        campaign_locations = client.notes.list_campaign_note_locations(campaign_id)
        print(f"  campaign note locations: total={campaign_locations.get('total')}")
        station_locations = client.notes.list_station_note_locations(campaign_id, station_id)
        print(f"  station note locations: total={station_locations.get('total')}")

        print("\nCreating a custom metadata-schema field (station scope)...")
        schema_field = client.metadata_schema.create_schema(
            scope="station",
            key=f"field_operator_{campaign_id}",
            label="Field Operator",
            field_type="string",
            help_text="Name of the person who installed/maintains this station.",
        )
        print(f"  metadata schema id={schema_field.get('id')} key={schema_field.get('key')}")

        print("\nDone.")
        print(f"campaign_id={campaign_id} station_id={station_id}")
        print("These are real resources on the target instance — clean them up when you're done with them.")
        return 0

    except UpstreamError as exc:
        print(f"\nFailed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
