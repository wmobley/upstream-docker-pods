from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_admin_user, get_viewer_user
from app.api.v1.schemas.metadata_schema import (
    MetadataSchemaCreate,
    MetadataSchemaListResponse,
    MetadataSchemaResponse,
    MetadataSchemaUpdate,
)
from app.api.v1.schemas.user import User
from app.db.models.metadata_schema import MetadataSchema
from app.db.repositories.metadata_schema_repository import MetadataSchemaRepository
from app.db.session import get_db


router = APIRouter(prefix="/metadata-schema", tags=["metadata-schema"])


@router.get("", response_model=MetadataSchemaListResponse)
def list_metadata_schema(
    scope: str | None = Query(None, description="Filter by scope (campaign, station, sensor)"),
    active_only: bool = Query(True, description="Return only active schema entries"),
    _user: User = Depends(get_viewer_user),
    db: Session = Depends(get_db),
) -> MetadataSchemaListResponse:
    repo = MetadataSchemaRepository(db)
    items = repo.list_schema(scope=scope, active_only=active_only)
    return MetadataSchemaListResponse(
        items=[
            MetadataSchemaResponse(
                id=item.id,
                scope=item.scope,
                key=item.key,
                label=item.label,
                field_type=item.field_type,
                required=item.required,
                help_text=item.help_text,
                units=item.units,
                ckan_field=item.ckan_field,
                ckan_mode=item.ckan_mode,
                order_index=item.order_index,
                active=item.active,
                options=item.options,
            )
            for item in items
        ]
    )


@router.get("/{schema_id}", response_model=MetadataSchemaResponse)
def get_metadata_schema(
    schema_id: int,
    _user: User = Depends(get_viewer_user),
    db: Session = Depends(get_db),
) -> MetadataSchemaResponse:
    repo = MetadataSchemaRepository(db)
    item = repo.get_by_id(schema_id)
    if not item:
        raise HTTPException(status_code=404, detail="Metadata schema not found")
    return MetadataSchemaResponse(
        id=item.id,
        scope=item.scope,
        key=item.key,
        label=item.label,
        field_type=item.field_type,
        required=item.required,
        help_text=item.help_text,
        units=item.units,
        ckan_field=item.ckan_field,
        ckan_mode=item.ckan_mode,
        order_index=item.order_index,
        active=item.active,
        options=item.options,
    )


@router.post("", response_model=MetadataSchemaResponse)
def create_metadata_schema(
    schema: MetadataSchemaCreate,
    _user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> MetadataSchemaResponse:
    repo = MetadataSchemaRepository(db)
    item = MetadataSchema(
        scope=schema.scope,
        key=schema.key,
        label=schema.label,
        field_type=schema.field_type,
        required=schema.required,
        help_text=schema.help_text,
        units=schema.units,
        ckan_field=schema.ckan_field,
        ckan_mode=schema.ckan_mode,
        order_index=schema.order_index,
        active=schema.active,
        options=schema.options,
    )
    item = repo.create(item)
    return MetadataSchemaResponse(
        id=item.id,
        scope=item.scope,
        key=item.key,
        label=item.label,
        field_type=item.field_type,
        required=item.required,
        help_text=item.help_text,
        units=item.units,
        ckan_field=item.ckan_field,
        ckan_mode=item.ckan_mode,
        order_index=item.order_index,
        active=item.active,
        options=item.options,
    )


@router.patch("/{schema_id}", response_model=MetadataSchemaResponse)
def update_metadata_schema(
    schema_id: int,
    schema: MetadataSchemaUpdate,
    _user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> MetadataSchemaResponse:
    repo = MetadataSchemaRepository(db)
    item = repo.get_by_id(schema_id)
    if not item:
        raise HTTPException(status_code=404, detail="Metadata schema not found")

    update_data = schema.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)

    item = repo.update(item)
    return MetadataSchemaResponse(
        id=item.id,
        scope=item.scope,
        key=item.key,
        label=item.label,
        field_type=item.field_type,
        required=item.required,
        help_text=item.help_text,
        units=item.units,
        ckan_field=item.ckan_field,
        ckan_mode=item.ckan_mode,
        order_index=item.order_index,
        active=item.active,
        options=item.options,
    )


@router.delete("/{schema_id}", status_code=204, response_class=Response, response_model=None)
def delete_metadata_schema(
    schema_id: int,
    _user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    repo = MetadataSchemaRepository(db)
    item = repo.get_by_id(schema_id)
    if not item:
        raise HTTPException(status_code=404, detail="Metadata schema not found")
    repo.delete(item)
    return Response(status_code=204)
