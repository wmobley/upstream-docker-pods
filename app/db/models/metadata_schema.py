from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MetadataSchema(Base):
    __tablename__ = "metadata_schema"
    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_metadata_schema_scope_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    scope: Mapped[str] = mapped_column(String, nullable=False, index=True)
    key: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    field_type: Mapped[str] = mapped_column(String, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    help_text: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    units: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ckan_field: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ckan_mode: Mapped[str] = mapped_column(String, nullable=False, default="extra")
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    options: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
