from types import SimpleNamespace

from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.routes.upload_file.upload_csv import (
    close_db_session_safely,
    normalize_client_request_id,
    snapshot_ckan_inputs,
)


def test_close_db_session_safely_contains_dead_connection_error() -> None:
    class BrokenSession:
        invalidated = False

        def close(self):
            raise SQLAlchemyError("connection closed")

        def invalidate(self):
            self.invalidated = True

    session = BrokenSession()

    close_db_session_safely(session, upload_event_id=5852)  # type: ignore[arg-type]

    assert session.invalidated is True


def test_normalize_client_request_id_accepts_only_uuid_values() -> None:
    value = "123e4567-e89b-12d3-a456-426614174000"

    assert normalize_client_request_id(value) == value
    assert normalize_client_request_id("not-a-request-id") is None
    assert normalize_client_request_id(None) is None


def test_snapshot_ckan_inputs_detaches_mutable_metadata() -> None:
    campaign = SimpleNamespace(
        id=7,
        name="Campaign Alpha",
        description="Campaign",
        contact_name="Owner",
        contact_email="owner@example.com",
        start_date=None,
        end_date=None,
        allocation="org-1",
        metadata={"funding": "team"},
    )
    station = SimpleNamespace(
        id=11,
        name="Station Bravo",
        description="Station",
        contact_name="Station Owner",
        contact_email="station@example.com",
        geometry={"type": "Point", "coordinates": [1, 2]},
        published_at=None,
        metadata={"local_code": "SB-01"},
    )
    sensor = SimpleNamespace(
        sensorid=5,
        alias="Air Temp",
        variablename="air_temperature",
        meta={"instrument": "XT-1"},
    )
    schema = [SimpleNamespace(key="local_code", ckan_field=None, ckan_mode="extra")]

    snapshots = snapshot_ckan_inputs(
        campaign,
        station,
        [sensor],
        schema,
        schema,
        schema,
    )

    campaign.metadata["funding"] = "changed"
    station.geometry["coordinates"][0] = 99
    sensor.meta["instrument"] = "changed"

    assert snapshots[0].meta == {"funding": "team"}
    assert snapshots[1].geometry["coordinates"] == [1, 2]
    assert snapshots[2][0].meta == {"instrument": "XT-1"}
