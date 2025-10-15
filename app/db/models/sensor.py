from typing import List, Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Sensor(Base):
    __tablename__ = "sensors"

    sensorid: Mapped[int] = mapped_column(primary_key=True, index=True)
    stationid: Mapped[int] = mapped_column(ForeignKey("stations.stationid"))
    alias: Mapped[Optional[str]] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()
    postprocess: Mapped[Optional[bool]] = mapped_column()
    postprocessscript: Mapped[Optional[str]] = mapped_column()
    units: Mapped[Optional[str]] = mapped_column()
    variablename: Mapped[Optional[str]] = mapped_column()
    upload_file_events_id: Mapped[int] = mapped_column(
        ForeignKey("upload_file_events.id", ondelete="CASCADE")
    )


    # relationships
    station: Mapped["Station"] = relationship("Station", back_populates="sensors")
    measurements: Mapped[List["Measurement"]] = relationship("Measurement", back_populates="sensor", lazy="dynamic")
    upload_file_event: Mapped["UploadFileEvent"] = relationship("UploadFileEvent")
    statistics: Mapped["SensorStatistics"] = relationship("SensorStatistics", back_populates="sensor")
