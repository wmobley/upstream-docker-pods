from __future__ import annotations

import json
from types import SimpleNamespace

from app.services.ckan_publish import (
    DATASET_HASH_EXTRA_KEY,
    DATASET_KEY_EXTRA_KEY,
    ensure_station_dataset,
    sync_sensor_resources,
)


def test_ensure_station_dataset_maps_campaign_top_level_metadata() -> None:
    captured: dict[str, object] = {}

    class FakeCKANClient:
        def create_or_update_dataset(self, **kwargs):
            captured["create_or_update_dataset"] = kwargs
            return {"id": "dataset-1", "name": "dataset-1", "resources": []}

        def ensure_dataset_visibility(self, **kwargs):
            captured["ensure_dataset_visibility"] = kwargs
            return {"id": "dataset-1"}

    settings = SimpleNamespace(UI_BASE_URL="https://ui.example.com")
    campaign = SimpleNamespace(
        id=7,
        name="Campaign Alpha",
        description="Campaign description",
        contact_name="Campaign Owner",
        contact_email="campaign@example.com",
        start_date=None,
        end_date=None,
        meta={"funding_contact": "Funding Team"},
    )
    station = SimpleNamespace(
        id=11,
        name="Station Bravo",
        description="Station description",
        contact_name="Station Owner",
        contact_email="station@example.com",
        geometry=None,
        published_at=None,
        meta={"local_code": "SB-01"},
    )
    station_schema = [
        SimpleNamespace(key="local_code", ckan_field=None, ckan_mode="extra"),
    ]
    campaign_schema = [
        SimpleNamespace(
            key="funding_contact",
            ckan_field="maintainer",
            ckan_mode="top_level",
        ),
    ]

    dataset, dataset_id, errors = ensure_station_dataset(
        settings=settings,
        ckan_client=FakeCKANClient(),
        tapis_token="token",
        campaign=campaign,
        station=station,
        owner_org="org-1",
        private=False,
        station_metadata_schema=station_schema,
        campaign_metadata_schema=campaign_schema,
    )

    assert errors == []
    assert dataset_id == "dataset-1"
    assert dataset is not None

    kwargs = captured["create_or_update_dataset"]
    assert isinstance(kwargs, dict)
    assert str(kwargs["name"]).startswith("campaign-alpha-station-bravo-")
    assert len(str(kwargs["name"]).rsplit("-", 1)[-1]) == 10
    assert kwargs["allow_existing_patch"] is True
    assert str(kwargs["suggested_name"]).endswith("-2")
    assert kwargs["extra_fields"]["maintainer"] == "Funding Team"
    extras = kwargs["extras"]
    assert {"key": DATASET_KEY_EXTRA_KEY, "value": "https://ui.example.com/campaigns/7/stations/11"} in extras
    hash_extra = next(item for item in extras if item["key"] == DATASET_HASH_EXTRA_KEY)
    assert len(hash_extra["value"]) == 10
    assert {"key": "meta:station:local_code", "value": "SB-01"} in extras


def test_ensure_station_dataset_allows_publish_conflict_options() -> None:
    captured: dict[str, object] = {}

    class FakeCKANClient:
        def create_or_update_dataset(self, **kwargs):
            captured["create_or_update_dataset"] = kwargs
            return {"id": "dataset-1", "name": kwargs["name"], "resources": []}

        def ensure_dataset_visibility(self, **kwargs):
            captured["ensure_dataset_visibility"] = kwargs
            return {"id": "dataset-1"}

    settings = SimpleNamespace(UI_BASE_URL="https://ui.example.com")
    campaign = SimpleNamespace(
        id=7,
        name="Campaign Alpha",
        description="Campaign description",
        contact_name=None,
        contact_email=None,
        start_date=None,
        end_date=None,
        meta={},
    )
    station = SimpleNamespace(
        id=11,
        name="Station Bravo",
        description="Station description",
        contact_name=None,
        contact_email=None,
        geometry=None,
        published_at=None,
        meta={},
    )

    dataset, dataset_id, errors = ensure_station_dataset(
        settings=settings,
        ckan_client=FakeCKANClient(),
        tapis_token="token",
        campaign=campaign,
        station=station,
        owner_org="org-1",
        private=False,
        dataset_name="Custom Dataset Name",
        allow_existing_patch=False,
    )

    assert errors == []
    assert dataset_id == "dataset-1"
    assert dataset is not None

    kwargs = captured["create_or_update_dataset"]
    assert isinstance(kwargs, dict)
    assert kwargs["name"] == "custom-dataset-name"
    assert kwargs["suggested_name"] == "custom-dataset-name-2"
    assert kwargs["allow_existing_patch"] is False


def test_sync_sensor_resources_maps_sensor_metadata_to_resource_fields() -> None:
    calls: list[dict[str, object]] = []

    class FakeCKANClient:
        def ensure_resource(self, **kwargs):
            calls.append(kwargs)
            return {"id": kwargs.get("resource_id") or kwargs["name"], "name": kwargs["name"]}

    settings = SimpleNamespace(
        UI_BASE_URL="https://ui.example.com",
        API_BASE_URL="https://api.example.com",
    )
    campaign = SimpleNamespace(id=7, name="Campaign Alpha")
    station = SimpleNamespace(id=11, name="Station Bravo")
    sensors = [
        SimpleNamespace(
            id=5,
            alias="Air Temp",
            variablename="air_temperature",
            meta={"instrument_model": "XT-1", "calibrated": True},
        )
    ]
    sensor_schema = [
        SimpleNamespace(
            key="instrument_model",
            ckan_field="instrument_model",
            ckan_mode="top_level",
        ),
        SimpleNamespace(
            key="calibrated",
            ckan_field=None,
            ckan_mode="extra",
        ),
    ]

    errors = sync_sensor_resources(
        settings=settings,
        ckan_client=FakeCKANClient(),
        tapis_token="token",
        campaign=campaign,
        station=station,
        dataset={"resources": []},
        dataset_id="dataset-1",
        sensors=sensors,
        sensor_metadata_schema=sensor_schema,
    )

    assert errors == []
    assert len(calls) == 2
    for call in calls:
        assert call["extra_fields"]["instrument_model"] == "XT-1"
        assert call["extra_fields"]["meta:sensor:calibrated"] == "True"


def test_ensure_station_dataset_uses_buffered_bbox_polygon_for_spatial() -> None:
    captured: dict[str, object] = {}

    class FakeCKANClient:
        def create_or_update_dataset(self, **kwargs):
            captured["create_or_update_dataset"] = kwargs
            return {"id": "dataset-1", "name": "dataset-1", "resources": []}

        def ensure_dataset_visibility(self, **kwargs):
            captured["ensure_dataset_visibility"] = kwargs
            return {"id": "dataset-1"}

    settings = SimpleNamespace(UI_BASE_URL="https://ui.example.com")
    campaign = SimpleNamespace(
        id=7,
        name="Campaign Alpha",
        description="Campaign description",
        contact_name=None,
        contact_email=None,
        start_date=None,
        end_date=None,
        meta={},
    )
    station = SimpleNamespace(
        id=11,
        name="Station Bravo",
        description="Station description",
        contact_name=None,
        contact_email=None,
        geometry={"type": "Point", "coordinates": [-95.1455382232693, 29.91312814548]},
        published_at=None,
        meta={},
    )

    dataset, dataset_id, errors = ensure_station_dataset(
        settings=settings,
        ckan_client=FakeCKANClient(),
        tapis_token="token",
        campaign=campaign,
        station=station,
        owner_org="org-1",
        private=False,
        station_metadata_schema=[],
        campaign_metadata_schema=[],
    )

    assert errors == []
    assert dataset_id == "dataset-1"
    assert dataset is not None

    kwargs = captured["create_or_update_dataset"]
    assert isinstance(kwargs, dict)
    spatial = json.loads(kwargs["extra_fields"]["spatial"])
    assert spatial["type"] == "Polygon"
    ring = spatial["coordinates"][0]
    assert len(ring) == 5
    west, south = ring[0]
    _, north = ring[1]
    east, _ = ring[2]
    assert west < station.geometry["coordinates"][0] < east
    assert south < station.geometry["coordinates"][1] < north
    assert abs((north - south) - (10 / 111_320)) < 1e-6
