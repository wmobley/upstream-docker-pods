import pytest

from app.services.ckan_service import CKANError, CKANService


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

    with pytest.raises(CKANError, match="does not match this Upstream station"):
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
