from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Sequence

from app.core.config import Settings
from app.services.ckan_service import CKANService, CKANError, _slugify

logger = logging.getLogger(__name__)


def ensure_station_dataset(
    *,
    settings: Settings,
    ckan_client: CKANService,
    tapis_token: str,
    campaign: Any,
    station: Any,
    owner_org: str | None,
    private: bool,
    station_metadata_schema: Sequence[Any] | None = None,
    campaign_metadata_schema: Sequence[Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    """
    Ensure a CKAN dataset exists for the given station and return the dataset payload,
    dataset id, and any errors encountered.
    """
    errors: list[str] = []
    dataset_name = _slugify(f"{campaign.name}-{station.name}")
    notes = station.description or f"Station {station.name} in campaign {campaign.name}"
    tags = {"upstream", _slugify(campaign.name), _slugify(station.name)}
    extras = [
        {"key": "campaign_id", "value": str(campaign.id)},
        {"key": "campaign_name", "value": campaign.name},
        {"key": "station_id", "value": str(station.id)},
        {"key": "station_name", "value": station.name},
    ]
    source_url = f"{settings.UI_BASE_URL.rstrip('/')}/campaigns/{campaign.id}/stations/{station.id}"
    extras.append({"key": "source", "value": source_url})

    spatial_value = None
    station_geometry = getattr(station, "geometry", None)
    if isinstance(station_geometry, dict) and station_geometry:
        spatial_value = json.dumps(station_geometry)

    version_value = None
    published_at = getattr(station, "published_at", None)
    if published_at:
        version_value = published_at.date().isoformat()
    elif getattr(campaign, "end_date", None):
        version_value = campaign.end_date.date().isoformat() if hasattr(campaign.end_date, "date") else str(campaign.end_date)
    elif getattr(campaign, "start_date", None):
        version_value = campaign.start_date.date().isoformat() if hasattr(campaign.start_date, "date") else str(campaign.start_date)

    extra_fields: dict[str, Any] = {
        "url": source_url,
        "author": campaign.contact_name or None,
        "author_email": campaign.contact_email or None,
        "maintainer": station.contact_name or campaign.contact_name or None,
        "maintainer_email": station.contact_email or campaign.contact_email or None,
        "temporal_coverage_start": campaign.start_date.isoformat() if campaign.start_date else None,
        "temporal_coverage_end": campaign.end_date.isoformat() if campaign.end_date else None,
        "spatial": spatial_value,
    }
    if version_value:
        extra_fields["version"] = version_value

    station_metadata = getattr(station, "meta", None) or {}
    campaign_metadata = getattr(campaign, "meta", None) or {}
    station_top_level, station_extras = _build_ckan_metadata(
        station_metadata,
        station_metadata_schema or [],
        prefix="meta:station:",
        allow_top_level=True,
    )
    campaign_top_level, campaign_extras = _build_ckan_metadata(
        campaign_metadata,
        campaign_metadata_schema or [],
        prefix="meta:campaign:",
        allow_top_level=True,
    )
    if station_extras:
        extras.extend(station_extras)
    if campaign_extras:
        extras.extend(campaign_extras)
    if station_top_level:
        extra_fields.update(station_top_level)
    if campaign_top_level:
        extra_fields.update(campaign_top_level)

    dataset: dict[str, Any] | None = None
    dataset_id: str | None = None

    try:
        dataset = ckan_client.create_or_update_dataset(
            token=tapis_token,
            name=dataset_name,
            title=f"{campaign.name} - {station.name}",
            owner_org=owner_org,
            notes=notes,
            tags=tags,
            extras=extras,
            private=private,
            extra_fields={k: v for k, v in extra_fields.items() if v is not None},
        )
        dataset_id = str(dataset.get("id") or dataset.get("name") or dataset_name)
        if dataset_id:
            ckan_client.ensure_dataset_visibility(
                token=tapis_token,
                dataset_id=dataset_id,
                private=private,
            )
    except CKANError as exc:
        message = f"Failed to register dataset for station {station.id} in CKAN: {exc}"
        logger.warning("%s", message)
        errors.append(message)
    except Exception as exc:  # pragma: no cover - defensive
        message = f"Unexpected error while ensuring CKAN dataset for station {station.id}: {exc}"
        logger.exception("%s", message)
        errors.append(message)

    return dataset, dataset_id, errors


def _sensor_identifier(sensor: Any) -> tuple[str, str]:
    sensor_id = getattr(sensor, "id", None) or getattr(sensor, "sensorid", None)
    sensor_label = getattr(sensor, "alias", None) or getattr(sensor, "variablename", None)
    # Sensor dictionaries from CSV ingestion
    if sensor_id is None and isinstance(sensor, dict):
        sensor_id = sensor.get("id") or sensor.get("sensorid")
        sensor_label = sensor.get("alias") or sensor.get("variablename")
    sensor_id_str = str(sensor_id) if sensor_id is not None else "unknown"
    label = str(sensor_label or f"sensor-{sensor_id_str}")
    return sensor_id_str, label


def sync_sensor_resources(
    *,
    settings: Settings,
    ckan_client: CKANService,
    tapis_token: str,
    campaign: Any,
    station: Any,
    dataset: dict[str, Any] | None,
    dataset_id: str | None,
    sensors: Sequence[Any] | Iterable[Any],
    sensor_metadata_schema: Sequence[Any] | None = None,
) -> list[str]:
    """
    Ensure CKAN resources exist for the provided sensors. Returns a list of warnings/errors.
    """
    errors: list[str] = []
    if not sensors or not dataset_id:
        return errors

    existing_resources_by_name: dict[str, dict[str, Any]] = {}
    if dataset and isinstance(dataset.get("resources"), list):
        for resource in dataset["resources"]:
            if isinstance(resource, dict):
                name = resource.get("name")
                if isinstance(name, str):
                    existing_resources_by_name[name] = resource

    ui_base = settings.UI_BASE_URL.rstrip("/")
    api_base = settings.API_BASE_URL.rstrip("/") if settings.API_BASE_URL else None

    def _upsert_resource(
        name: str,
        url: str,
        description: str,
        format_: str,
        sensor_identifier: str,
        extra_fields: dict[str, Any] | None = None,
    ) -> None:
        existing = existing_resources_by_name.get(name)
        resource_id = str(existing.get("id")) if existing and existing.get("id") else None
        try:
            resource = ckan_client.ensure_resource(
                token=tapis_token,
                dataset_id=str(dataset_id),
                name=name,
                url=url,
                description=description,
                format_=format_,
                resource_id=resource_id,
                extra_fields=extra_fields,
            )
            existing_resources_by_name[name] = resource
        except CKANError as exc:
            message = (
                f"Failed to register resource {name} for sensor {sensor_identifier} in CKAN: {exc}"
            )
            logger.warning("%s", message)
            errors.append(message)
        except Exception as exc:  # pragma: no cover - defensive
            message = (
                f"Unexpected error while registering resource {name} for sensor "
                f"{sensor_identifier} in CKAN: {exc}"
            )
            logger.exception("%s", message)
            errors.append(message)

    for sensor in sensors:
        sensor_id, sensor_label = _sensor_identifier(sensor)
        sensor_slug = _slugify(f"{station.name}-{sensor_label}") or f"sensor-{sensor_id}"
        sensor_metadata = getattr(sensor, "meta", None) or {}
        sensor_top_level, sensor_extras = _build_ckan_metadata(
            sensor_metadata,
            sensor_metadata_schema or [],
            prefix="meta:sensor:",
            allow_top_level=True,
        )
        resource_extra_fields = {
            **sensor_top_level,
            **_extras_to_field_map(sensor_extras),
        }

        sensor_ui_name = f"{sensor_slug}-ui"
        sensor_ui_url = f"{ui_base}/campaigns/{campaign.id}/stations/{station.id}/sensors/{sensor_id}"
        sensor_ui_description = f"Interactive upstream view for sensor {sensor_label} at station {station.name}."
        _upsert_resource(
            sensor_ui_name,
            sensor_ui_url,
            sensor_ui_description,
            "HTML",
            sensor_id,
            resource_extra_fields,
        )

        if not api_base:
            continue

        sensor_api_name = f"{sensor_slug}-measurements"
        sensor_api_url = (
            f"{api_base}/api/v1/campaigns/{campaign.id}/stations/{station.id}/sensors/{sensor_id}/measurements"
        )
        sensor_api_description = (
            f"Measurement API endpoint (GeoJSON) for sensor {sensor_label} at station {station.name}."
        )
        _upsert_resource(
            sensor_api_name,
            sensor_api_url,
            sensor_api_description,
            "GeoJSON",
            sensor_id,
            resource_extra_fields,
        )

    return errors


def _build_ckan_metadata(
    metadata: dict[str, Any],
    schema_items: Sequence[Any],
    *,
    prefix: str,
    allow_top_level: bool,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    top_level: dict[str, Any] = {}
    extras: list[dict[str, str]] = []
    if not metadata or not schema_items:
        return top_level, extras

    for item in schema_items:
        key = _schema_attr(item, "key")
        if not key or key not in metadata:
            continue
        value = metadata.get(key)
        if value is None:
            continue
        ckan_field = _schema_attr(item, "ckan_field")
        ckan_mode = (_schema_attr(item, "ckan_mode") or "extra").lower()
        if allow_top_level and ckan_field and ckan_mode == "top_level":
            top_level[ckan_field] = value
        else:
            extras.append({"key": f"{prefix}{key}", "value": _serialize_metadata_value(value)})

    return top_level, extras


def _schema_attr(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _serialize_metadata_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value)
        except Exception:
            return str(value)
    return str(value)


def _extras_to_field_map(extras: Sequence[dict[str, str]]) -> dict[str, str]:
    return {
        item["key"]: item["value"]
        for item in extras
        if isinstance(item, dict) and "key" in item and "value" in item
    }


__all__ = ["ensure_station_dataset", "sync_sensor_resources"]
