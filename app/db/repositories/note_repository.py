from datetime import datetime, timezone
from typing import Optional

from geoalchemy2 import WKTElement
from sqlalchemy.orm import Session

from app.db.models.note import Note, NoteScope


class NoteRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        scope: NoteScope,
        content: str,
        created_by: str,
        campaign_id: int,
        station_id: Optional[int] = None,
        sensor_id: Optional[int] = None,
        measurement_id: Optional[int] = None,
        location: Optional[str] = None,
    ) -> Note:
        note = Note(
            scope=scope,
            content=content,
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
            campaign_id=campaign_id,
            station_id=station_id,
            sensor_id=sensor_id,
            measurement_id=measurement_id,
            location=WKTElement(location, srid=4326) if location else None,
        )
        self.db.add(note)
        self.db.commit()
        self.db.refresh(note)
        return note

    def get(self, note_id: int) -> Note | None:
        return self.db.query(Note).filter(Note.noteid == note_id).first()

    def list_by_campaign(self, campaign_id: int) -> tuple[list[Note], int]:
        q = self.db.query(Note).filter(
            Note.campaign_id == campaign_id,
            Note.scope == NoteScope.CAMPAIGN,
        ).order_by(Note.created_at.desc())
        return q.all(), q.count()

    def list_by_station(self, campaign_id: int, station_id: int) -> tuple[list[Note], int]:
        q = self.db.query(Note).filter(
            Note.campaign_id == campaign_id,
            Note.station_id == station_id,
            Note.scope == NoteScope.STATION,
        ).order_by(Note.created_at.desc())
        return q.all(), q.count()

    def list_by_measurement(self, campaign_id: int, station_id: int, measurement_id: int) -> tuple[list[Note], int]:
        q = self.db.query(Note).filter(
            Note.campaign_id == campaign_id,
            Note.station_id == station_id,
            Note.measurement_id == measurement_id,
            Note.scope == NoteScope.MEASUREMENT,
        ).order_by(Note.created_at.desc())
        return q.all(), q.count()

    def list_by_sensor(self, campaign_id: int, station_id: int, sensor_id: int) -> tuple[list[Note], int]:
        q = self.db.query(Note).filter(
            Note.campaign_id == campaign_id,
            Note.station_id == station_id,
            Note.sensor_id == sensor_id,
            Note.scope == NoteScope.SENSOR,
        ).order_by(Note.created_at.desc())
        return q.all(), q.count()

    def update(self, note_id: int, content: str, *, location: Optional[str] = None) -> Note | None:
        note = self.db.query(Note).filter(Note.noteid == note_id).first()
        if not note:
            return None
        note.content = content
        note.location = WKTElement(location, srid=4326) if location else None  # type: ignore[assignment]
        self.db.commit()
        self.db.refresh(note)
        return note

    def list_all_by_station(self, station_id: int) -> list[Note]:
        """Return all notes associated with a station (station-scoped and measurement-scoped)."""
        return (
            self.db.query(Note)
            .filter(Note.station_id == station_id)
            .order_by(Note.scope, Note.created_at)
            .all()
        )

    def list_all_by_campaign(self, campaign_id: int) -> list[Note]:
        """Return every note in a campaign, across all scopes."""
        return (
            self.db.query(Note)
            .filter(Note.campaign_id == campaign_id)
            .order_by(Note.scope, Note.created_at)
            .all()
        )

    def delete(self, note_id: int) -> bool:
        note = self.db.query(Note).filter(Note.noteid == note_id).first()
        if not note:
            return False
        self.db.delete(note)
        self.db.commit()
        return True
