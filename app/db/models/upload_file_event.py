from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UploadFileEvent(Base):
    __tablename__ = "upload_file_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    time: Mapped[datetime] = mapped_column()

    # Chunked upload-session tracking (nullable so existing rows and legacy
    # clients remain valid). A single chunked upload shares one
    # upload_session_id across all of its chunk receipts.
    upload_session_id: Mapped[Optional[str]] = mapped_column(default=None)
    campaign_id: Mapped[Optional[int]] = mapped_column(default=None)
    station_id: Mapped[Optional[int]] = mapped_column(default=None)
    chunk_index: Mapped[Optional[int]] = mapped_column(default=None)
    total_chunks: Mapped[Optional[int]] = mapped_column(default=None)

    # Per-chunk audit counts. NULL until a chunk finishes inserting rows.
    measurement_rows_read: Mapped[Optional[int]] = mapped_column(default=None)
    measurement_values_attempted: Mapped[Optional[int]] = mapped_column(default=None)
    measurement_values_inserted: Mapped[Optional[int]] = mapped_column(default=None)
    measurement_values_skipped_duplicate: Mapped[Optional[int]] = mapped_column(
        default=None
    )

    # Set once on the receipt that successfully finalizes the session.
    finalized: Mapped[bool] = mapped_column(default=False)
    finalized_at: Mapped[Optional[datetime]] = mapped_column(default=None)

    # relationships
    # measurements: Mapped[list("Measurement")] = relationship(lazy="joined") # back_populates="upload_file_event",
    # sensors: Mapped[list("Sensor")] = relationship(lazy="joined") # back_populates="upload_file_event",
