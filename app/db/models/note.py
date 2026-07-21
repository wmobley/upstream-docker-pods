from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class NoteScope(str, PyEnum):
    CAMPAIGN = "campaign"
    STATION = "station"
    SENSOR = "sensor"
    MEASUREMENT = "measurement"


class Note(Base):
    __tablename__ = "notes"

    noteid: Mapped[int] = mapped_column(primary_key=True, index=True)
    scope: Mapped[NoteScope] = mapped_column(SAEnum(NoteScope, name="note_scope"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.campaignid", ondelete="CASCADE"), nullable=False
    )
    station_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("stations.stationid", ondelete="CASCADE"), nullable=True
    )
    sensor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sensors.sensorid", ondelete="CASCADE"), nullable=True
    )
    measurement_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("measurements.measurementid", ondelete="CASCADE"), nullable=True
    )

    campaign: Mapped["Campaign"] = relationship(back_populates="notes")
    station: Mapped[Optional["Station"]] = relationship(back_populates="notes")
    sensor: Mapped[Optional["Sensor"]] = relationship(back_populates="notes")
