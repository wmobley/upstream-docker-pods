from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MeasurementIdentity(Base):
    """Stable global identity for a measurement across sensor partitions."""

    __tablename__ = "measurement_identity"

    measurementid: Mapped[int] = mapped_column(primary_key=True)
    sensorid: Mapped[int] = mapped_column(
        ForeignKey("sensors.sensorid", ondelete="CASCADE"), nullable=False
    )
