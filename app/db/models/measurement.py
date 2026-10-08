from datetime import datetime
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Measurement(Base):
    __tablename__ = "measurements"

    # The partitioned table is uniquely identified by measurementid + sensorid.
    # measurementid remains globally unique through measurement_identity, while
    # the composite ORM key lets SQLAlchemy target the correct child partition.
    measurementid: Mapped[int] = mapped_column(
        primary_key=True, index=True, autoincrement=True
    )
    sensorid: Mapped[int] = mapped_column(
        ForeignKey("sensors.sensorid", ondelete="CASCADE"), primary_key=True
    )
    stationid: Mapped[int] = mapped_column()
    collectiontime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    measurementvalue: Mapped[float] = mapped_column()
    geometry: Mapped[Geometry] = mapped_column(Geometry("POINT", srid=4326))
    variablename: Mapped[Optional[str]] = mapped_column()
    variabletype: Mapped[Optional[str]] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()
    # relationships
    sensor: Mapped["Sensor"] = relationship(
        back_populates="measurements", lazy="joined"
    )
    upload_file_events_id: Mapped[int] = mapped_column(
        ForeignKey("upload_file_events.id", ondelete="CASCADE")
    )
    upload_file_event: Mapped["UploadFileEvent"] = relationship(
        lazy="joined"
    )  #  back_populates="measurements"
