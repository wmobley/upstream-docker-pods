from datetime import datetime
from typing import List, Optional

import geoalchemy2
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    campaignid: Mapped[int] = mapped_column(primary_key=True, index=True)
    campaignname: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None] = mapped_column()
    contactname: Mapped[str | None] = mapped_column()
    contactemail: Mapped[str | None] = mapped_column()
    startdate: Mapped[datetime | None] = mapped_column()
    enddate: Mapped[datetime | None] = mapped_column()
    allocation: Mapped[str] = mapped_column()
    bbox_west: Mapped[float | None] = mapped_column()
    bbox_east: Mapped[float | None] = mapped_column()
    bbox_south: Mapped[float | None] = mapped_column()
    bbox_north: Mapped[float | None] = mapped_column()
    geometry: Mapped[geoalchemy2.types.Geometry] = mapped_column(geoalchemy2.types.Geometry("GEOMETRY", srid=4326))
    # publishing fields
    is_published: Mapped[bool] = mapped_column(default=False)
    published_at: Mapped[datetime | None] = mapped_column()
    # relationships
    stations: Mapped[List["Station"]] = relationship(
        back_populates="campaign"
    )