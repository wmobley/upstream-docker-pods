#!/usr/bin/env python3
import os
import re

def fix_optional_in_file(file_path):
    """Fix Optional[Type] to Type | None in a Python file."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()

        # Track if any changes were made
        original_content = content

        # Replace Optional[Type] with Type | None
        # This regex handles nested brackets like Optional[List[str]]
        def replace_optional(match):
            inner_type = match.group(1)
            return f"{inner_type} | None"

        # Handle nested Optional types
        while True:
            new_content = re.sub(r'Optional\[([^\[\]]+(?:\[[^\[\]]*\])*[^\[\]]*)\]', replace_optional, content)
            if new_content == content:
                break
            content = new_content

        # Write back if changed
        if content != original_content:
            with open(file_path, 'w') as f:
                f.write(content)
            print(f"Fixed: {file_path}")
            return True
        else:
            print(f"No changes needed: {file_path}")
            return False

    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False

def main():
    # Files that need fixing
    files_to_fix = [
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/services/measurement_service.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/services/sensor_service.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/services/campaign_service.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/api/v1/routes/campaigns/root.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/api/v1/routes/campaigns/campaign_station_sensor_measurements.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/api/v1/routes/campaigns/campaign_stations.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/api/v1/routes/campaigns/campaign_station_sensors.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/api/v1/schemas/upload_csv_validators.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/api/v1/schemas/campaign.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/api/v1/schemas/measurement.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/db/repositories/measurement_repository.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/db/repositories/sensor_repository.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/db/repositories/campaign_repository.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/pytas/models/schemas.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/db/repositories/station_repository.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/db/models/measurement.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/db/models/sensor.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/db/models/station.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/db/models/campaign.py",
        "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app/db/models/sensor_statistics.py"
    ]

    fixed_count = 0
    for file_path in files_to_fix:
        if os.path.exists(file_path):
            if fix_optional_in_file(file_path):
                fixed_count += 1
        else:
            print(f"File not found: {file_path}")

    print(f"\nFixed {fixed_count} files")

if __name__ == "__main__":
    main()