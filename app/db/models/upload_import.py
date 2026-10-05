from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.upload_import_backfill import UploadImportBackfill


class UploadImport(Base):
    """Durable control-plane state for an asynchronous bulk upload."""

    __tablename__ = "upload_imports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campaign_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    station_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    owner_username: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="created")
    ingestion_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="standard", server_default="standard"
    )
    storage_key: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    sensors_storage_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    values_attempted: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    values_inserted: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    worker_token: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    sealed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    data_loaded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Chunk ingestion and expensive statistics/geometry work have independent
    # lifecycles. The mapping is retained so post-processing does not need the
    # original sensor CSV after chunk storage is cleaned up.
    sensor_mapping: Mapped[Optional[dict[str, int]]] = mapped_column(
        JSON, nullable=True
    )
    post_processing_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending"
    )
    # Statistics and station geometry are separate retryable stages. A failed
    # geometry refresh must not force a repeat of all sensor statistics.
    post_processing_stage: Mapped[Optional[str]] = mapped_column(
        String(24), nullable=True, default="statistics"
    )
    post_processing_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    post_processing_token: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True
    )
    post_processing_lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    post_processing_error: Mapped[Optional[str]] = mapped_column(
        String(2000), nullable=True
    )
    post_processing_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    post_processing_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    chunks: Mapped[list["UploadImportChunk"]] = relationship(
        back_populates="upload_import",
        cascade="all, delete-orphan",
        order_by="UploadImportChunk.chunk_index",
    )
    backfill: Mapped["UploadImportBackfill | None"] = relationship(
        back_populates="upload_import", uselist=False, cascade="all, delete-orphan"
    )


class UploadImportChunk(Base):
    """Immutable manifest and processing receipt for one measurement chunk."""

    __tablename__ = "upload_import_chunks"
    __table_args__ = (
        UniqueConstraint("import_id", "chunk_index", name="uq_upload_import_chunk_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    import_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("upload_imports.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Relative to the import directory; chunk_index is the uniqueness boundary.
    storage_key: Mapped[str] = mapped_column(String(128), nullable=False)
    processed: Mapped[bool] = mapped_column(nullable=False, default=False)
    upload_event_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("upload_file_events.id", ondelete="SET NULL"), nullable=True
    )
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    values_attempted: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    values_inserted: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    upload_import: Mapped[UploadImport] = relationship(back_populates="chunks")


# Register the one-to-one model whenever the existing import model is imported.
from app.db.models.upload_import_backfill import UploadImportBackfill  # noqa: E402,F401
