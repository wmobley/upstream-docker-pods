import pytest

from app.services.ckan_service import CKANDatasetNameConflict, CKANError, CKANService


def test_create_or_update_dataset_patches_matching_existing_dataset() -> None:
    calls: list[dict[str, object]] = []

    class FakeCKANService(CKANService):
        def _request(self, **kwargs):  # type: ignore[override]
            calls.append(kwargs)
            path = kwargs["path"]
            if path == "/api/3/action/package_show":
                return {
                    "id": "dataset-id",
                    "name": "dataset-name",
                    "extras": [
                        {"key": "campaign_id", "value": "7"},
                        {"key": "station_id", "value": "11"},
                        {"key": "upstream_dataset_hash", "value": "abc123def0"},
                    ],
                }
            if path == "/api/3/action/package_patch":
                return {"id": "dataset-id", "name": "dataset-name"}
            raise AssertionError(f"Unexpected path {path}")

    service = FakeCKANService(base_url="https://ckan.example.com")

    result = service.create_or_update_dataset(
        token="token",
        name="dataset-name",
        title="Dataset",
        owner_org="org",
        notes="notes",
        tags=["upstream"],
        extras=[
            {"key": "campaign_id", "value": "7"},
            {"key": "station_id", "value": "11"},
            {"key": "upstream_dataset_hash", "value": "abc123def0"},
        ],
    )

    assert result["id"] == "dataset-id"
    # The dataset already exists, so package_create should never be called.
    assert [call["path"] for call in calls] == [
        "/api/3/action/package_show",
        "/api/3/action/package_patch",
    ]
    assert calls[-1]["json"]["id"] == "dataset-name"


def test_create_or_update_dataset_rejects_existing_dataset_for_other_station() -> None:
    class FakeCKANService(CKANService):
        def _request(self, **kwargs):  # type: ignore[override]
            path = kwargs["path"]
            if path == "/api/3/action/package_show":
                return {
                    "id": "dataset-id",
                    "name": "dataset-name",
                    "extras": [
                        {"key": "campaign_id", "value": "99"},
                        {"key": "station_id", "value": "11"},
                        {"key": "upstream_dataset_hash", "value": "different"},
                    ],
                }
            raise AssertionError(f"Unexpected path {path}")

    service = FakeCKANService(base_url="https://ckan.example.com")

    with pytest.raises(CKANError, match="Suggested new dataset name: 'dataset-name-2'"):
        service.create_or_update_dataset(
            token="token",
            name="dataset-name",
            title="Dataset",
            owner_org="org",
            notes="notes",
            tags=["upstream"],
            extras=[
                {"key": "campaign_id", "value": "7"},
                {"key": "station_id", "value": "11"},
                {"key": "upstream_dataset_hash", "value": "abc123def0"},
            ],
        )


def test_create_or_update_dataset_creates_when_none_exists() -> None:
    calls: list[dict[str, object]] = []

    class FakeCKANService(CKANService):
        def _request(self, **kwargs):  # type: ignore[override]
            calls.append(kwargs)
            path = kwargs["path"]
            if path == "/api/3/action/package_show":
                raise CKANError("Not found")
            if path == "/api/3/action/package_create":
                return {"id": "dataset-id", "name": "dataset-name"}
            raise AssertionError(f"Unexpected path {path}")

    service = FakeCKANService(base_url="https://ckan.example.com")

    result = service.create_or_update_dataset(
        token="token",
        name="dataset-name",
        title="Dataset",
        owner_org="org",
        notes="notes",
        tags=["upstream"],
        extras=[{"key": "campaign_id", "value": "7"}],
    )

    assert result["id"] == "dataset-id"
    assert [call["path"] for call in calls] == [
        "/api/3/action/package_show",
        "/api/3/action/package_create",
    ]


def test_create_or_update_dataset_falls_back_to_patch_on_create_race() -> None:
    calls: list[dict[str, object]] = []

    class FakeCKANService(CKANService):
        def _request(self, **kwargs):  # type: ignore[override]
            calls.append(kwargs)
            path = kwargs["path"]
            if path == "/api/3/action/package_show":
                if sum(1 for call in calls if call["path"] == "/api/3/action/package_show") == 1:
                    raise CKANError("Not found")
                return {
                    "id": "dataset-id",
                    "name": "dataset-name",
                    "extras": [
                        {"key": "campaign_id", "value": "7"},
                        {"key": "upstream_dataset_hash", "value": "abc123def0"},
                    ],
                }
            if path == "/api/3/action/package_create":
                raise CKANError("Validation error: dataset already exists")
            if path == "/api/3/action/package_patch":
                return {"id": "dataset-id", "name": "dataset-name"}
            raise AssertionError(f"Unexpected path {path}")

    service = FakeCKANService(base_url="https://ckan.example.com")

    result = service.create_or_update_dataset(
        token="token",
        name="dataset-name",
        title="Dataset",
        owner_org="org",
        notes="notes",
        tags=["upstream"],
        extras=[
            {"key": "campaign_id", "value": "7"},
            {"key": "upstream_dataset_hash", "value": "abc123def0"},
        ],
    )

    assert result["id"] == "dataset-id"
    assert [call["path"] for call in calls] == [
        "/api/3/action/package_show",
        "/api/3/action/package_create",
        "/api/3/action/package_show",
        "/api/3/action/package_patch",
    ]


def test_create_or_update_dataset_requires_explicit_patch_for_matching_existing_dataset() -> None:
    calls: list[dict[str, object]] = []

    class FakeCKANService(CKANService):
        def _request(self, **kwargs):  # type: ignore[override]
            calls.append(kwargs)
            path = kwargs["path"]
            if path == "/api/3/action/package_show":
                return {
                    "id": "dataset-id",
                    "name": "dataset-name",
                    "extras": [
                        {"key": "campaign_id", "value": "7"},
                        {"key": "station_id", "value": "11"},
                        {"key": "upstream_dataset_hash", "value": "abc123def0"},
                    ],
                }
            raise AssertionError(f"Unexpected path {path}")

    service = FakeCKANService(base_url="https://ckan.example.com")

    with pytest.raises(CKANDatasetNameConflict) as exc_info:
        service.create_or_update_dataset(
            token="token",
            name="dataset-name",
            title="Dataset",
            owner_org="org",
            notes="notes",
            tags=["upstream"],
            extras=[
                {"key": "campaign_id", "value": "7"},
                {"key": "station_id", "value": "11"},
                {"key": "upstream_dataset_hash", "value": "abc123def0"},
            ],
            allow_existing_patch=False,
        )

    assert exc_info.value.dataset_name == "dataset-name"
    assert exc_info.value.suggested_name == "dataset-name-2"
    assert "patch_existing_ckan_dataset=true" in str(exc_info.value)
    assert [call["path"] for call in calls] == ["/api/3/action/package_show"]
