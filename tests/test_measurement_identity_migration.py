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


def test_measurement_identity_migration_seeds_before_installing_trigger() -> None:
    source = MIGRATION.read_text()

    seed_position = source.index("INSERT INTO {IDENTITY_TABLE}")
    trigger_position = source.index("CREATE OR REPLACE FUNCTION {TRIGGER_FUNCTION}")

    assert seed_position < trigger_position
    assert "BEFORE INSERT ON measurements" in source
    assert "measurement identity % is already registered to sensor" in source
