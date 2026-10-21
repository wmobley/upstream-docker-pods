import io
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import UploadFile

from app.utils.bulk_upload_csv import (
    BULK_INSERT_SQL,
    _parse_stage_row,
    process_measurements_file_bulk,
)


def make_upload_file(content: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content.encode("utf-8")), filename="data.csv")


def test_parse_stage_row_keeps_only_nonblank_sensor_values() -> None:
    per_alias: dict[str, int] = {}
    staged = _parse_stage_row(
        {
            "collectiontime": "2024-01-01T00:00:00",
            "Lat_deg": "30.1",
            "Lon_deg": "-97.7",
            "temp": "21.5",
            "humidity": "",
        },
        source_row_ordinal=4,
        station_id=2,
        alias_to_sensorid_map={"temp": 11, "humidity": 12},
        station_timezone="UTC",
        per_alias=per_alias,
    )

    assert staged["source_row_ordinal"] == 4
    assert staged["stationid"] == 2
    assert staged["sensor_values"] == {"11": 21.5}
    assert per_alias == {"temp": 1}


def test_bulk_processor_reports_set_based_insert_counts() -> None:
    session = MagicMock()
    counts = SimpleNamespace(values_attempted=2, values_inserted=1)
    session.execute.side_effect = [None, None, None, SimpleNamespace(one=lambda: counts)]

    result = process_measurements_file_bulk(
        make_upload_file(
            "collectiontime,Lat_deg,Lon_deg,temp\n"
            "2024-01-01T00:00:00,30.1,-97.7,21.5\n"
            "2024-01-01T00:00:00,30.1,-97.7,22.5\n"
        ),
        station_id=2,
        alias_to_sensorid_map={"temp": 11},
        upload_event_id=9,
        session=session,
        station_timezone="UTC",
    )

    assert result.rows_read == 2
    assert result.values_attempted == 2
    assert result.values_inserted == 1
    assert result.values_skipped_duplicate == 1
    session.commit.assert_called_once()
    stage_insert = session.execute.call_args_list[2].args[0]
    assert stage_insert._bindparams["lat"].type.python_type is float
    assert stage_insert._bindparams["lon"].type.python_type is float


def test_bulk_sql_reuses_staged_geometry_and_keeps_source_deduplication() -> None:
    sql = str(BULK_INSERT_SQL)

    assert "stage.geometry" in sql
    assert "ST_MakePoint" not in sql
    assert "DISTINCT ON (sensorid, collectiontime)" in sql
    assert "ON CONFLICT (sensorid, collectiontime) DO NOTHING" in sql
