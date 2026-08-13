import pytest

from app.services.ckan_service import CKANDatasetNameConflict, CKANError, CKANService


def test_create_or_update_dataset_patches_matching_existing_dataset() -> None:
    calls: list[dict[str, object]] = []

    class FakeCKANService(CKANService):
        def _request(self, **kwargs):  # type: ignore[override]
            calls.append(kwargs)
            path = kwargs["path"]
            if path == "/api/3/action/package_create":
                raise CKANError("Validation error: dataset already exists")
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
    patch_call = calls[-1]
    assert patch_call["path"] == "/api/3/action/package_patch"
    assert patch_call["json"]["id"] == "dataset-name"


def test_create_or_update_dataset_rejects_existing_dataset_for_other_station() -> None:
    class FakeCKANService(CKANService):
        def _request(self, **kwargs):  # type: ignore[override]
            path = kwargs["path"]
            if path == "/api/3/action/package_create":
                raise CKANError("Validation error: dataset already exists")
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


def test_create_or_update_dataset_requires_explicit_patch_for_matching_existing_dataset() -> None:
    class FakeCKANService(CKANService):
        def _request(self, **kwargs):  # type: ignore[override]
            path = kwargs["path"]
            if path == "/api/3/action/package_create":
                raise CKANError("Validation error: dataset already exists")
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
