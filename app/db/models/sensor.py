from datetime import datetime
from typing import List, Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Sensor(Base):
    __tablename__ = "sensors"

    sensorid: Mapped[int] = mapped_column(primary_key=True, index=True)
    stationid: Mapped[int] = mapped_column(ForeignKey("stations.stationid"))
    alias: Mapped[str | None] = mapped_column()
    description: Mapped[str | None] = mapped_column()
    postprocess: Mapped[bool | None] = mapped_column()
    postprocessscript: Mapped[str | None] = mapped_column()
    units: Mapped[str | None] = mapped_column()
    variablename: Mapped[str | None] = mapped_column()
    upload_file_events_id: Mapped[int] = mapped_column(
        ForeignKey("upload_file_events.id", ondelete="CASCADE")
    )

    # publishing fields
    is_published: Mapped[bool] = mapped_column(default=False)
    published_at: Mapped[datetime | None] = mapped_column()

    # relationships
    station: Mapped["Station"] = relationship("Station", back_populates="sensors")
    measurements: Mapped[List["Measurement"]] = relationship("Measurement", back_populates="sensor", lazy="dynamic")
    upload_file_event: Mapped["UploadFileEvent"] = relationship("UploadFileEvent")
    statistics: Mapped["SensorStatistics"] = relationship("SensorStatistics", back_populates="sensor")
