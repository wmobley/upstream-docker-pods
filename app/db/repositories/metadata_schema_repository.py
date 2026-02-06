from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.db.models.metadata_schema import MetadataSchema


class MetadataSchemaRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_schema(
        self,
        *,
        scope: str | None = None,
        active_only: bool = True,
    ) -> list[MetadataSchema]:
        query = self.db.query(MetadataSchema)
        if scope:
            query = query.filter(MetadataSchema.scope == scope)
        if active_only:
            query = query.filter(MetadataSchema.active.is_(True))
        result = query.order_by(MetadataSchema.order_index.asc(), MetadataSchema.id.asc()).all()
        if not isinstance(result, list):
            return []
        return list(result)

    def get_by_id(self, schema_id: int) -> Optional[MetadataSchema]:
        return self.db.query(MetadataSchema).filter(MetadataSchema.id == schema_id).first()

    def create(self, schema: MetadataSchema) -> MetadataSchema:
        self.db.add(schema)
        self.db.commit()
        self.db.refresh(schema)
        return schema

    def update(self, schema: MetadataSchema) -> MetadataSchema:
        self.db.commit()
        self.db.refresh(schema)
        return schema

    def delete(self, schema: MetadataSchema) -> None:
        self.db.delete(schema)
        self.db.commit()
