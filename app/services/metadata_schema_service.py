from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.db.models.metadata_schema import MetadataSchema
from app.db.repositories.metadata_schema_repository import MetadataSchemaRepository


class MetadataSchemaService:
    def __init__(self, repository: MetadataSchemaRepository):
        self.repository = repository

    def list_schema(self, *, scope: str | None = None, active_only: bool = True) -> list[MetadataSchema]:
        return self.repository.list_schema(scope=scope, active_only=active_only)

    def validate_metadata(self, scope: str, metadata: dict[str, Any] | None) -> list[str]:
        if not metadata:
            metadata = {}

        schema_items = self.repository.list_schema(scope=scope, active_only=True)
        schema_by_key = {item.key: item for item in schema_items}
        errors: list[str] = []

        for key in metadata.keys():
            if key not in schema_by_key:
                errors.append(f"Unknown metadata field '{key}' for scope '{scope}'")

        for item in schema_items:
            value = metadata.get(item.key)
            if item.required and (item.key not in metadata or value in (None, "")):
                errors.append(f"Missing required metadata field '{item.key}' for scope '{scope}'")
                continue

            if item.key not in metadata:
                continue

            if not _validate_type(item.field_type, value, item.options):
                errors.append(f"Invalid value for metadata field '{item.key}' (expected {item.field_type})")

        return errors


def _validate_type(field_type: str, value: Any, options: dict[str, Any] | list[Any] | None) -> bool:
    if value is None:
        return True

    field_type = (field_type or "").lower()

    if field_type == "string":
        return isinstance(value, str)
    if field_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if field_type == "bool":
        return isinstance(value, bool)
    if field_type == "date":
        return isinstance(value, (str, datetime, date))
    if field_type == "json":
        return isinstance(value, (dict, list))
    if field_type == "enum":
        if not isinstance(value, str):
            return False
        allowed = None
        if isinstance(options, list):
            allowed = options
        elif isinstance(options, dict):
            if isinstance(options.get("values"), list):
                allowed = options.get("values")
        if allowed is None:
            return True
        return value in allowed

    # Unknown type: accept to avoid blocking admin-defined fields
    return True
