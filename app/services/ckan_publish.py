from __future__ import annotations

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

    def _upsert_resource(name: str, url: str, description: str, format_: str, sensor_identifier: str) -> None:
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

        sensor_ui_name = f"{sensor_slug}-ui"
        sensor_ui_url = f"{ui_base}/campaigns/{campaign.id}/stations/{station.id}/sensors/{sensor_id}"
        sensor_ui_description = f"Interactive upstream view for sensor {sensor_label} at station {station.name}."
        _upsert_resource(sensor_ui_name, sensor_ui_url, sensor_ui_description, "HTML", sensor_id)

        if not api_base:
            continue

        sensor_api_name = f"{sensor_slug}-measurements"
        sensor_api_url = (
            f"{api_base}/api/v1/campaigns/{campaign.id}/stations/{station.id}/sensors/{sensor_id}/measurements"
        )
        sensor_api_description = (
            f"Measurement API endpoint (GeoJSON) for sensor {sensor_label} at station {station.name}."
        )
        _upsert_resource(sensor_api_name, sensor_api_url, sensor_api_description, "GeoJSON", sensor_id)

    return errors


__all__ = ["ensure_station_dataset", "sync_sensor_resources"]
