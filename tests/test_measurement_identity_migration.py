from pathlib import Path

MIGRATION = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20261006_measurement_identity.py"
)


def test_measurement_identity_migration_is_headed_from_bounded_backfill() -> None:
    source = MIGRATION.read_text()

    assert 'revision: str = "20261006_measurement_identity"' in source
    assert (
        'down_revision: Union[str, Sequence[str], None] = "20261005_bounded_materialize"'
        in source
    )
    assert 'IDENTITY_TABLE = "measurement_identity"' in source


def test_measurement_identity_migration_defers_large_seed_and_trigger() -> None:
    source = MIGRATION.read_text()

    assert "The existing 64M-row table is intentionally not copied" in source
    assert "SELECT measurementid, sensorid\n            FROM measurements" not in source
    assert "CREATE TRIGGER {TRIGGER_NAME}" not in source
    assert "CREATE OR REPLACE FUNCTION {TRIGGER_FUNCTION}" in source
    assert "measurement identity % is already registered to sensor" in source


def test_develop_seed_helper_is_guarded_and_resumable() -> None:
    source = (
        MIGRATION.parents[2] / "scripts" / "seed_measurement_identity_develop.py"
    ).read_text()

    assert "ENV=develop and --confirm-develop" in source
    assert "measurement_identity_seed_state" in source
    assert "ON CONFLICT (measurementid) DO NOTHING" in source
    assert "SET cursor = :cursor, phase = 'seeding'" in source
    assert "measurements={source_count}, identity={identity_count}" in source
    assert "CREATE TRIGGER {TRIGGER_NAME}" in source
