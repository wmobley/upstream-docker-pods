from pathlib import Path


MIGRATION = Path(__file__).parents[1] / "alembic/versions/20261019_idempotent_sensor_statistics_refresh.py"


def test_sensor_statistics_refresh_seeds_rows_with_conflict_guard() -> None:
    source = MIGRATION.read_text()

    assert "CREATE OR REPLACE FUNCTION refresh_outdated_sensor_statistics" in source
    assert "ON CONFLICT (sensorid) DO NOTHING" in source
    assert "Two uploads can refresh the same sensor concurrently" in source
