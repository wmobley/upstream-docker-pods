from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.upload_import import UploadImport


class UploadImportBackfill(Base):
    """Durable lifecycle state for an isolated shadow-table backfill."""

    __tablename__ = "upload_import_backfills"

    import_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("upload_imports.id", ondelete="CASCADE"), primary_key=True
    )
    raw_table_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    shadow_table_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    phase: Mapped[str] = mapped_column(String(24), nullable=False, default="staging")
    staged_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    staged_values: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    shadow_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    shadow_values: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    merged_values: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    merge_cursor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    target_collisions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lease_token: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    validated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    merged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    upload_import: Mapped["UploadImport"] = relationship(back_populates="backfill")
