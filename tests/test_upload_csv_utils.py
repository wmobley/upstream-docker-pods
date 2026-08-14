import io
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile

from app.utils.upload_csv import (
    _is_empty_upload,
    process_measurements_file,
    process_sensors_file,
)


def make_upload_file(content: str, filename: str = "upload.csv") -> UploadFile:
    return UploadFile(file=io.BytesIO(content.encode("utf-8")), filename=filename)


def test_is_empty_upload_true_for_zero_byte_file() -> None:
    assert _is_empty_upload(make_upload_file("")) is True


def test_is_empty_upload_false_for_file_with_content() -> None:
    file = make_upload_file("alias,units\nRiver Stage,ft\n")
    assert _is_empty_upload(file) is False
    # Reading position must be restored so callers can still parse the file.
    assert file.file.tell() == 0


def test_process_sensors_file_returns_empty_map_for_blank_upload(mock_db_session: MagicMock) -> None:
    result = process_sensors_file(
        make_upload_file("", filename="blob"),
        station_id=1,
        upload_event_id=1,
        session=mock_db_session,
    )

    assert result == {}
    mock_db_session.query.assert_not_called()


def test_process_measurements_file_returns_zero_for_blank_upload(mock_db_session: MagicMock) -> None:
    result = process_measurements_file(
        make_upload_file("", filename="blob"),
        station_id=1,
        alias_to_sensorid_map={"River Stage": 1},
        upload_event_id=1,
        session=mock_db_session,
    )

    assert result.rows_read == 0
    assert result.errors == []
    mock_db_session.execute.assert_not_called()


def test_process_sensors_file_still_raises_validation_error_for_missing_alias_column(
    mock_db_session: MagicMock,
) -> None:
    file = make_upload_file("units\nft\n")

    with pytest.raises(Exception):
        process_sensors_file(file, station_id=1, upload_event_id=1, session=mock_db_session)
