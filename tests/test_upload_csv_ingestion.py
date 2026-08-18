import io
from datetime import datetime
from unittest.mock import MagicMock, patch

from starlette.datastructures import UploadFile as StarletteUploadFile

# Import models so SQLAlchemy's string-based relationship registry resolves.
import app.db.models.campaign  # noqa: F401
import app.db.models.measurement  # noqa: F401
import app.db.models.note  # noqa: F401
import app.db.models.sensor  # noqa: F401
import app.db.models.station  # noqa: F401
from app.api.v1.routes.upload_file.upload_csv import (
    create_upload_event,
    find_finalized_receipt,
    get_session_receipts,
    post_sensor_and_measurement,
    successful_receipt_chunk_indexes,
)
from app.db.models.upload_file_event import UploadFileEvent
from app.utils.upload_csv import (
    BatchInsertResult,
    MeasurementsProcessingResult,
    process_batch,
    process_measurements_file,
)


def make_upload_file(content: bytes, filename: str = "data.csv") -> StarletteUploadFile:
    return StarletteUploadFile(file=io.BytesIO(content), filename=filename)


def make_session() -> MagicMock:
    session = MagicMock()
    session.commit.return_value = None
    return session


def make_execute_result(rows: int) -> MagicMock:
    """Result whose RETURNING rows count equals ``rows`` inserted values."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = [1] * rows
    return result


class TestProcessBatch:
    def test_empty_batch(self):
        session = make_session()
        result = process_batch([], session)
        assert isinstance(result, BatchInsertResult)
        assert result.values_attempted == 0
        assert result.values_inserted == 0
        assert result.values_skipped_duplicate == 0

    def test_insert_counts_use_returned_rows(self):
        session = make_session()
        session.execute.return_value = make_execute_result(3)
        batch = [
            {
                "sensorid": 1,
                "collectiontime": datetime(2024, 1, 1, 12, 0, 0),
                "measurementvalue": 1.0,
            },
            {
                "sensorid": 1,
                "collectiontime": datetime(2024, 1, 1, 12, 0, 1),
                "measurementvalue": 2.0,
            },
            {
                "sensorid": 1,
                "collectiontime": datetime(2024, 1, 1, 12, 0, 2),
                "measurementvalue": 3.0,
            },
            {
                "sensorid": 1,
                "collectiontime": datetime(2024, 1, 1, 12, 0, 3),
                "measurementvalue": 4.0,
            },
        ]
        result = process_batch(batch, session)
        assert result.values_attempted == 4
        assert result.values_inserted == 3
        assert result.values_skipped_duplicate == 1
        assert batch == []


class TestProcessMeasurementsFile:
    MEASUREMENT_HEADER = "collectiontime,Lon_deg,Lat_deg,temp,humid\n"

    def _run(self, csv_text: str, alias_map=None, station_timezone=None):
        session = make_session()
        session.execute.return_value = make_execute_result(1)
        file = make_upload_file(csv_text.encode())
        alias_map = alias_map or {"temp": 10, "humid": 11}
        return process_measurements_file(
            file,
            station_id=7,
            alias_to_sensorid_map=alias_map,
            upload_event_id=1,
            session=session,
            station_timezone=station_timezone,
        )

    def test_counts_rows_and_values(self):
        csv_text = (
            self.MEASUREMENT_HEADER
            + "2024-01-01 12:00:00,30.0,-97.0,22.5,\n"
            + "2024-01-01 12:00:01,30.0,-97.0,23.1,55\n"
            + "2024-01-01 12:00:02,30.0,-97.0,,56\n"
        )
        result = self._run(csv_text)
        assert isinstance(result, MeasurementsProcessingResult)
        assert result.rows_read == 3
        assert result.values_attempted == 4  # temp:2 + humid:2
        assert result.per_alias == {"temp": 2, "humid": 2}
        assert result.errors == []

    def test_blank_rows_counted_as_read_but_not_attempted(self):
        csv_text = self.MEASUREMENT_HEADER + "2024-01-01 12:00:00,30.0,-97.0,,\n"
        result = self._run(csv_text)
        assert result.rows_read == 1
        assert result.values_attempted == 0
        assert result.values_inserted == 0
        assert result.values_skipped_duplicate == 0

    def test_empty_blob_is_not_an_error(self):
        result = self._run("")
        assert result.rows_read == 0
        assert result.values_attempted == 0
        assert result.values_inserted == 0
        assert result.errors == []

    def test_missing_alias_column_reports_error(self):
        csv_text = (
            "collectiontime,Lon_deg,Lat_deg,other\n2024-01-01 12:00:00,30.0,-97.0,5\n"
        )
        result = self._run(csv_text)
        assert result.errors, "expected an error for missing alias column"
        assert result.values_attempted == 0

    def test_skipped_duplicates_derive_from_attempted_minus_inserted(self):
        session = make_session()
        session.execute.return_value = make_execute_result(1)
        file = make_upload_file(
            (
                self.MEASUREMENT_HEADER
                + "2024-01-01 12:00:00,30.0,-97.0,22.5,\n"
                + "2024-01-01 12:00:00,30.0,-97.0,23.0,\n"  # duplicate (sensorid, collectiontime)
            ).encode()
        )
        result = process_measurements_file(
            file,
            station_id=7,
            alias_to_sensorid_map={"temp": 10},
            upload_event_id=1,
            session=session,
        )
        assert result.values_attempted == 2
        assert result.values_inserted == 1
        assert result.values_skipped_duplicate == 1

    def _inserted_collectiontimes(self, session):
        """Return the collectiontime values sent to the insert statement."""
        stmt = session.execute.call_args[0][0]
        compiled = stmt.compile()
        return [
            value for key, value in compiled.params.items() if "collectiontime" in key
        ]

    def test_naive_local_times_localized_in_station_timezone(self):
        from datetime import timezone

        session = make_session()
        session.execute.return_value = make_execute_result(1)
        file = make_upload_file(
            (
                self.MEASUREMENT_HEADER
                + "2024-01-01 12:00:00,30.0,-97.0,22.5,\n"  # CST (UTC-6) -> 18:00 UTC
                + "2024-06-01 12:00:00,30.0,-97.0,25.0,\n"  # CDT (UTC-5) -> 17:00 UTC
            ).encode()
        )
        result = process_measurements_file(
            file,
            station_id=7,
            alias_to_sensorid_map={"temp": 10},
            upload_event_id=1,
            session=session,
            station_timezone="America/Chicago",
        )
        assert result.values_attempted == 2
        values = self._inserted_collectiontimes(session)
        assert len(values) == 2
        jan, june = values
        # January: Chicago is CST (UTC-6); June: CDT (UTC-5).
        assert jan.utcoffset().total_seconds() == -6 * 3600
        assert june.utcoffset().total_seconds() == -5 * 3600
        assert jan.astimezone(timezone.utc).isoformat() == "2024-01-01T18:00:00+00:00"
        assert june.astimezone(timezone.utc).isoformat() == "2024-06-01T17:00:00+00:00"

    def test_aware_values_pass_through_regardless_of_station_timezone(self):
        from datetime import timezone

        session = make_session()
        session.execute.return_value = make_execute_result(1)
        file = make_upload_file(
            (
                self.MEASUREMENT_HEADER + "2024-01-01T12:00:00Z,30.0,-97.0,22.5,\n"
            ).encode()
        )
        result = process_measurements_file(
            file,
            station_id=7,
            alias_to_sensorid_map={"temp": 10},
            upload_event_id=1,
            session=session,
            station_timezone="America/Chicago",
        )
        assert result.values_attempted == 1
        (value,) = self._inserted_collectiontimes(session)
        assert value.astimezone(timezone.utc).isoformat() == "2024-01-01T12:00:00+00:00"

    def test_naive_values_default_to_utc_without_station_timezone(self):
        from datetime import timezone

        session = make_session()
        session.execute.return_value = make_execute_result(1)
        file = make_upload_file(
            (
                self.MEASUREMENT_HEADER + "2024-01-01 12:00:00,30.0,-97.0,22.5,\n"
            ).encode()
        )
        result = process_measurements_file(
            file,
            station_id=7,
            alias_to_sensorid_map={"temp": 10},
            upload_event_id=1,
            session=session,
        )
        assert result.values_attempted == 1
        (value,) = self._inserted_collectiontimes(session)
        assert value.astimezone(timezone.utc).isoformat() == "2024-01-01T12:00:00+00:00"


class TestSessionReceiptHelpers:
    def test_successful_receipt_chunk_indexes(self):
        session = make_session()
        session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            UploadFileEvent(id=5, chunk_index=0, measurement_values_inserted=10),
            UploadFileEvent(
                id=6, chunk_index=1, measurement_values_inserted=0
            ),  # 0 is a valid success
            UploadFileEvent(
                id=7, chunk_index=2, measurement_values_inserted=None
            ),  # incomplete
            UploadFileEvent(
                id=8, chunk_index=None, measurement_values_inserted=5
            ),  # no index
        ]
        indexes = successful_receipt_chunk_indexes(
            session, campaign_id=1, station_id=2, upload_session_id="sess"
        )
        assert indexes == {0, 1}

    def test_find_finalized_receipt(self):
        session = make_session()
        session.query.return_value.filter.return_value.first.return_value = (
            UploadFileEvent(id=3, finalized=True)
        )
        receipt = find_finalized_receipt(
            session, campaign_id=1, station_id=2, upload_session_id="sess"
        )
        assert receipt is not None
        assert receipt.id == 3

    def test_find_finalized_receipt_none(self):
        session = make_session()
        session.query.return_value.filter.return_value.first.return_value = None
        receipt = find_finalized_receipt(
            session, campaign_id=1, station_id=2, upload_session_id="sess"
        )
        assert receipt is None

    def test_get_session_receipts_ordered_newest_first(self):
        session = make_session()
        session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            UploadFileEvent(id=2),
            UploadFileEvent(id=1),
        ]
        receipts = get_session_receipts(
            session, campaign_id=1, station_id=2, upload_session_id="sess"
        )
        assert [r.id for r in receipts] == [2, 1]


class TestCreateUploadEvent:
    def test_records_session_metadata(self):
        session = make_session()
        event = create_upload_event(
            session,
            campaign_id=1,
            station_id=2,
            upload_session_id="sess-abc",
            chunk_index=3,
            total_chunks=4,
        )
        assert event.campaign_id == 1
        assert event.station_id == 2
        assert event.upload_session_id == "sess-abc"
        assert event.chunk_index == 3
        assert event.total_chunks == 4
        assert not event.finalized  # default False applied at flush time
        session.add.assert_called_once()
        session.commit.assert_called_once()


def make_request_kwargs(**overrides):
    """Common mocked deps for calling post_sensor_and_measurement directly."""
    kwargs = {
        "campaign_id": 1,
        "station_id": 2,
        "upload_file_sensors": make_upload_file(b"sensors", "sensors.csv"),
        "upload_file_measurements": make_upload_file(
            b"measurements", "measurements.csv"
        ),
        "background_tasks": MagicMock(),
        "db": make_session(),
        "current_user": MagicMock(),
        "tapis_token": None,
    }
    kwargs.update(overrides)
    return kwargs


def patch_route_deps(
    alias_map=None, measurements_result=None, receipts=None, finalized_receipt=None
):
    alias_map = alias_map or {"temp": 10}
    measurements_result = measurements_result or MeasurementsProcessingResult(
        rows_read=2, values_attempted=2, values_inserted=2
    )
    if receipts is None:
        receipts = []
    fake_event = UploadFileEvent(
        id=42,
        campaign_id=1,
        station_id=2,
        upload_session_id="sess-1",
        chunk_index=0,
        total_chunks=1,
    )
    patch_station_service = patch(
        "app.api.v1.routes.upload_file.upload_csv.StationService"
    )
    patch_successful = patch(
        "app.api.v1.routes.upload_file.upload_csv.successful_receipt_chunk_indexes",
        return_value=set(range(len(receipts))),
    )
    return [
        patch(
            "app.api.v1.routes.upload_file.upload_csv.create_upload_event",
            return_value=fake_event,
        ),
        patch(
            "app.api.v1.routes.upload_file.upload_csv.process_sensors_file",
            return_value=alias_map,
        ),
        patch(
            "app.api.v1.routes.upload_file.upload_csv.process_measurements_file",
            return_value=measurements_result,
        ),
        patch("app.api.v1.routes.upload_file.upload_csv.update_sensor_statistics"),
        patch_station_service,
        patch_successful,
        patch(
            "app.api.v1.routes.upload_file.upload_csv.find_finalized_receipt",
            return_value=finalized_receipt,
        ),
    ], patch_station_service


class TestPostSensorAndMeasurement:
    @staticmethod
    def _run(**overrides):
        patches, _ = patch_route_deps(**overrides.pop("_patch_kwargs", {}))
        from contextlib import ExitStack

        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            return post_sensor_and_measurement(**make_request_kwargs(**overrides))

    def test_legacy_single_request_finalizes_and_runs_post_processing(self):
        response = self._run()

        assert response.finalized is True
        assert response.post_processing.status == "completed"
        assert response.post_processing.statistics_refreshed is True
        assert response.post_processing.station_geometry_refreshed is True
        assert response.ckan_sync.status == "missing_tapis_token"
        assert response.audit.measurement_rows_read == 2
        assert response.audit.measurement_values_inserted == 2
        assert response.upload_event_id is not None

    def test_non_final_chunk_skips_post_processing_and_ckan(self):
        response = self._run(
            upload_session_id="sess-1",
            finalize_upload=False,
            chunk_index=0,
            total_chunks=2,
        )

        assert response.finalized is False
        assert response.post_processing.status == "not_finalized"
        assert response.post_processing.statistics_refreshed is False
        assert response.post_processing.station_geometry_refreshed is False
        assert response.ckan_sync.status == "not_finalized"

    def test_final_chunk_with_all_receipts_finalizes(self):
        response = self._run(
            _patch_kwargs={"receipts": [0, 1]},
            upload_session_id="sess-1",
            finalize_upload=True,
            chunk_index=1,
            total_chunks=2,
        )

        assert response.finalized is True
        assert response.post_processing.status == "completed"
        assert response.post_processing.statistics_refreshed is True
        assert response.post_processing.station_geometry_refreshed is True

    def test_final_chunk_missing_receipts_not_finalized(self):
        response = self._run(
            _patch_kwargs={"receipts": [0]},
            upload_session_id="sess-1",
            finalize_upload=True,
            chunk_index=1,
            total_chunks=2,
        )

        assert response.finalized is False
        assert response.post_processing.status == "skipped_incomplete_upload"
        assert response.ckan_sync.status == "skipped_incomplete_upload"
        assert response.errors, "expected incompleteness error"
        assert any("chunk" in e.message for e in response.errors)

    def test_already_finalized_session_is_idempotent(self):
        finalized = UploadFileEvent(
            id=9, finalized=True, finalized_at=datetime(2024, 1, 1)
        )
        response = self._run(
            _patch_kwargs={"finalized_receipt": finalized},
            upload_session_id="sess-1",
            finalize_upload=True,
            chunk_index=1,
            total_chunks=2,
        )

        assert response.finalized is True
        assert response.post_processing.status == "already_finalized"
        assert response.ckan_sync.status == "already_finalized"
        assert response.post_processing.statistics_refreshed is False

    def test_default_finalize_true_for_chunked_single_chunk(self):
        response = self._run(
            _patch_kwargs={"receipts": [0]},
            upload_session_id="sess-1",
            chunk_index=0,
            total_chunks=1,
        )
        assert response.finalized is True
        assert response.post_processing.status == "completed"
