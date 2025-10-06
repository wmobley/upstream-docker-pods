from datetime import datetime
from typing import List, Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
import geoalchemy2
from app.db.base import Base


class Station(Base):
    __tablename__ = "stations"

    stationid: Mapped[int] = mapped_column(primary_key=True, index=True)
    campaignid: Mapped[int] = mapped_column(
        ForeignKey("campaigns.campaignid"), nullable=True
    )
    stationname: Mapped[str] = mapped_column(unique=True)
    projectid: Mapped[str | None] = mapped_column()
    description: Mapped[str | None] = mapped_column()
    contactname: Mapped[str | None] = mapped_column()
    contactemail: Mapped[str | None] = mapped_column()
    active: Mapped[bool | None] = mapped_column()
    startdate: Mapped[datetime | None] = mapped_column()


    # Station type
    station_type: Mapped[str] = mapped_column()  # 'static' or 'mobile'

    # Location for static stations
    geometry: Mapped[geoalchemy2.types.Geometry] = mapped_column(geoalchemy2.types.Geometry("GEOMETRY", srid=4326))

    # publishing fields
    is_published: Mapped[bool] = mapped_column(default=False)
    published_at: Mapped[datetime | None] = mapped_column()

    # relationships
    campaign: Mapped["Campaign"] = relationship(
        back_populates="stations"
    )
    sensors: Mapped[List["Sensor"]] = relationship(
        back_populates="station"
    )
