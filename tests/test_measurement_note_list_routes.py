from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_viewer_user
from app.api.v1.routes.campaigns.campaign_station_sensor_measurement_notes_by_sensor import (
    _service,
)
from app.api.v1.schemas.note import (
    ListMeasurementNotesResponse,
    MeasurementNoteItem,
)
from app.api.v1.schemas.user import User
from app.main import app


def test_list_measurement_notes_by_sensor_route_returns_timestamped_items():
    service = MagicMock()
    service.list_measurement_notes_by_sensor.return_value = ListMeasurementNotesResponse(
        items=[
            MeasurementNoteItem(
                id=7,
                scope="measurement",
                content="chart point observation",
                created_by="alice",
                created_at=datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc),
                campaign_id=1,
                station_id=2,
                sensor_id=None,
                measurement_id=3,
                measurement_timestamp=datetime(2026, 9, 16, 18, 30, tzinfo=timezone.utc),
            ),
        ],
        total=1,
    )
    app.dependency_overrides[_service] = lambda: service
    app.dependency_overrides[get_viewer_user] = lambda: User(username="alice", role="VIEWER")

    try:
        response = TestClient(app).get(
            "/api/v1/campaigns/1/stations/2/sensors/4/measurement-notes"
        )
    finally:
        app.dependency_overrides.pop(_service, None)
        app.dependency_overrides.pop(get_viewer_user, None)

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["measurement_timestamp"] == "2026-09-16T18:30:00Z"
    service.list_measurement_notes_by_sensor.assert_called_once_with(1, 2, 4)
