from pathlib import Path


MIGRATION = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20261018_bounded_station_geometry.py"
)


def test_station_geometry_migration_uses_bounded_extent_without_full_refresh() -> None:
    source = MIGRATION.read_text()

    assert 'revision: str = "20261018_bounded_station_geom"' in source
    assert (
        'down_revision: Union[str, Sequence[str], None] = "20261006_measurement_identity"'
        in source
    )
    assert "ST_Extent(m.geometry)" in source
    assert "ST_SetSRID" in source
    assert "ST_Collect(geometry)" not in source
    assert "JOIN measurements AS m ON s.sensorid = m.sensorid" in source
    assert "AND m.geometry IS NOT NULL" in source
    assert "SELECT update_station_geometry(stationid) FROM stations" not in source


def test_station_geometry_migration_preserves_empty_station_behavior() -> None:
    source = MIGRATION.read_text()

    assert "IF NOT FOUND THEN" in source
    assert "SET geometry = NULL" in source
