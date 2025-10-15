from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey
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
    projectid: Mapped[Optional[str]] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()
    contactname: Mapped[Optional[str]] = mapped_column()
    contactemail: Mapped[Optional[str]] = mapped_column()
    active: Mapped[Optional[bool]] = mapped_column()
    startdate: Mapped[Optional[datetime]] = mapped_column()


    # Station type
    station_type: Mapped[str] = mapped_column()  # 'static' or 'mobile'

    # Location for static stations
    geometry: Mapped[geoalchemy2.types.Geometry] = mapped_column(geoalchemy2.types.Geometry("GEOMETRY", srid=4326))
    published: Mapped[bool] = mapped_column("is_published", Boolean, nullable=False, default=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # relationships
    campaign: Mapped["Campaign"] = relationship(
        back_populates="stations"
    )
    sensors: Mapped[List["Sensor"]] = relationship(
        back_populates="station"
    )
