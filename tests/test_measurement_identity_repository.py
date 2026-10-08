from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.api.v1.schemas.measurement import MeasurementUpdate
from app.db.models.measurement import Measurement
from app.db.models.measurement_identity import MeasurementIdentity
from app.db.models.note import Note
from app.db.repositories.measurement_repository import MeasurementRepository
from app.db.repositories.note_repository import NoteRepository


def test_measurement_uses_partition_key_as_composite_orm_identity() -> None:
    assert set(Measurement.__table__.primary_key.columns.keys()) == {
        "measurementid",
        "sensorid",
    }


def test_note_measurement_fk_targets_global_identity_table() -> None:
    foreign_keys = Note.__table__.c.measurement_id.foreign_keys

    assert {str(key.target_fullname) for key in foreign_keys} == {
        "measurement_identity.measurementid"
    }
    assert MeasurementIdentity.__table__.c.measurementid.primary_key


def test_get_measurement_resolves_sensor_before_partitioned_lookup() -> None:
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = 27
    measurement = object()
    db.get.return_value = measurement

    result = MeasurementRepository(db).get_measurement(123)

    assert result is measurement
    db.get.assert_called_once_with(Measurement, (123, 27))


def test_get_measurement_returns_none_without_identity() -> None:
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None

    result = MeasurementRepository(db).get_measurement(123)

    assert result is None
    db.get.assert_not_called()


def test_delete_measurement_removes_global_identity_after_measurement() -> None:
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = 27
    existing = Measurement(measurementid=123, sensorid=27)
    db.get.return_value = existing

    assert MeasurementRepository(db).delete_measurement(123)

    db.delete.assert_called_once_with(existing)
    db.query.assert_called_once_with(MeasurementIdentity)
    db.commit.assert_called_once()


@pytest.mark.parametrize("partial", [False, True])
def test_update_measurement_rejects_sensor_change(partial: bool) -> None:
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = 27
    existing = Measurement(measurementid=123, sensorid=27)
    db.get.return_value = existing
    request = MeasurementUpdate(
        sensorid=99,
        collectiontime=datetime(2025, 1, 1, tzinfo=timezone.utc),
        geometry="POINT(0 0)",
        measurementvalue=1.0,
        variabletype="temperature",
    )

    with pytest.raises(ValueError, match="Sensor ID cannot be changed"):
        MeasurementRepository(db).update_measurement(123, request, partial=partial)

    db.commit.assert_not_called()


def test_measurement_notes_by_sensor_joins_identity_and_partition_key() -> None:
    db = MagicMock()
    query = db.query.return_value
    query.join.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = []

    result = NoteRepository(db).list_measurement_notes_by_sensor(1, 2, 27)

    assert result == []
    assert query.join.call_count == 2
    assert query.join.call_args_list[0].args[0] is MeasurementIdentity
    assert query.join.call_args_list[1].args[0] is Measurement
    assert any(
        "measurement_identity.sensorid" in str(clause)
        for clause in query.filter.call_args.args
    )
