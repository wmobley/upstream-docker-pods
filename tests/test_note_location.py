"""Tests for the measurement-note independent location feature.

See docs/design/2026-07-23-measurement-note-location.md.
"""
from unittest.mock import MagicMock

import pytest
from geoalchemy2 import WKTElement

import app.main  # noqa: F401 - imports the full model graph so Note's relationships resolve

from app.db.models.note import Note, NoteScope
from app.db.repositories.note_repository import NoteRepository
from app.services.note_service import NoteService
from app.api.v1.schemas.note import MeasurementNoteCreate, MeasurementNoteUpdate, NoteCreate, NoteUpdate


WKT = "POINT(-97.7431 30.2672)"


def test_measurement_note_create_schema_has_location():
    request = MeasurementNoteCreate(content="plume traced upstream", location=WKT)
    assert request.location == WKT


def test_base_note_create_schema_has_no_location_field():
    # Structural guarantee from the design: campaign/station/sensor routes use
    # the base schema, which has no location field to send one through at all.
    assert "location" not in NoteCreate.model_fields
    assert "location" not in NoteUpdate.model_fields
    assert "location" in MeasurementNoteCreate.model_fields
    assert "location" in MeasurementNoteUpdate.model_fields


def test_repository_create_persists_wkt_location():
    db = MagicMock()
    repo = NoteRepository(db)

    repo.create(
        scope=NoteScope.MEASUREMENT,
        content="plume traced upstream",
        created_by="alice",
        campaign_id=1,
        station_id=2,
        measurement_id=3,
        location=WKT,
    )

    added_note = db.add.call_args[0][0]
    assert isinstance(added_note, Note)
    assert isinstance(added_note.location, WKTElement)
    assert added_note.location.desc == WKT
    assert added_note.location.srid == 4326


def test_repository_create_without_location_leaves_it_none():
    db = MagicMock()
    repo = NoteRepository(db)

    repo.create(
        scope=NoteScope.CAMPAIGN,
        content="general observation",
        created_by="alice",
        campaign_id=1,
    )

    added_note = db.add.call_args[0][0]
    assert added_note.location is None


def test_repository_update_sets_and_clears_location():
    db = MagicMock()
    existing = Note(noteid=1, scope=NoteScope.MEASUREMENT, content="old", created_by="alice", campaign_id=1)
    db.query.return_value.filter.return_value.first.return_value = existing
    repo = NoteRepository(db)

    updated = repo.update(1, "new content", location=WKT)
    assert updated is existing
    assert isinstance(existing.location, WKTElement)
    assert existing.location.desc == WKT

    # Full-replacement semantics: omitting/None clears it.
    repo.update(1, "new content again")
    assert existing.location is None


def test_service_location_to_point_round_trips_coordinates():
    service = NoteService(MagicMock())
    point = service._location_to_point(WKTElement(WKT, srid=4326))
    assert point is not None
    assert point.type == "Point"
    assert point.coordinates[0] == pytest.approx(-97.7431)
    assert point.coordinates[1] == pytest.approx(30.2672)


def test_service_location_to_point_none_when_absent():
    service = NoteService(MagicMock())
    assert service._location_to_point(None) is None


def test_create_measurement_note_passes_location_to_repository():
    repo = MagicMock()
    repo.create.return_value = Note(noteid=1, scope=NoteScope.MEASUREMENT, content="x", created_by="alice", campaign_id=1)
    service = NoteService(repo)

    service.create_measurement_note(
        MeasurementNoteCreate(content="plume traced upstream", location=WKT),
        campaign_id=1,
        station_id=2,
        measurement_id=3,
        username="alice",
        location=WKT,
    )

    repo.create.assert_called_once()
    assert repo.create.call_args.kwargs["location"] == WKT


def test_update_passes_location_to_repository():
    from datetime import datetime, timezone

    repo = MagicMock()
    note = Note(
        noteid=1,
        scope=NoteScope.MEASUREMENT,
        content="old",
        created_by="alice",
        created_at=datetime.now(timezone.utc),
        campaign_id=1,
    )
    repo.get.return_value = note
    repo.update.return_value = note
    service = NoteService(repo)

    service.update(1, MeasurementNoteUpdate(content="new", location=WKT), username="alice", location=WKT)

    repo.update.assert_called_once_with(1, "new", location=WKT)
