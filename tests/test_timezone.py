"""Unit tests for app.utils.timezone.localize_collectiontime."""

from datetime import datetime

import pandas as pd
import pytest
from zoneinfo import ZoneInfoNotFoundError

from app.utils.timezone import localize_collectiontime


class TestLocalizeCollectiontime:
    def test_naive_value_interpreted_in_station_timezone(self):
        value = datetime(2026, 1, 15, 14, 30, 0)  # naive
        result = localize_collectiontime(value, "America/Chicago")
        assert result.tzinfo is not None
        # January: Chicago is UTC-6, so the instant is 20:30 UTC.
        assert result.utcoffset().total_seconds() == -6 * 3600
        assert result.isoformat() == "2026-01-15T14:30:00-06:00"

    def test_dst_summer_offset(self):
        value = datetime(2026, 7, 15, 14, 30, 0)
        result = localize_collectiontime(value, "America/Chicago")
        # July: Chicago is UTC-5 (CDT).
        assert result.utcoffset().total_seconds() == -5 * 3600

    def test_aware_value_passes_through_unchanged(self):
        value = datetime(2026, 1, 15, 20, 30, 0, tzinfo=__import__("zoneinfo").ZoneInfo("UTC"))
        result = localize_collectiontime(value, "America/Chicago")
        assert result == value

    def test_aware_offset_value_passes_through(self):
        value = datetime.fromisoformat("2026-01-15T14:30:00+05:00")
        result = localize_collectiontime(value, "America/Chicago")
        assert result == value
        assert result.utcoffset().total_seconds() == 5 * 3600

    def test_iso_string_input(self):
        result = localize_collectiontime("2026-01-15T14:30:00", "America/Chicago")
        assert result.isoformat() == "2026-01-15T14:30:00-06:00"

    def test_iso_string_with_z_input(self):
        result = localize_collectiontime("2026-01-15T14:30:00Z", "UTC")
        assert result.tzinfo is not None
        assert result.isoformat() == "2026-01-15T14:30:00+00:00"

    def test_pandas_timestamp_input(self):
        value = pd.Timestamp("2026-01-15 14:30:00")
        result = localize_collectiontime(value, "America/Chicago")
        assert isinstance(result, datetime)
        assert result.utcoffset().total_seconds() == -6 * 3600

    def test_pandas_timestamp_aware_input(self):
        value = pd.Timestamp("2026-01-15T14:30:00Z")
        result = localize_collectiontime(value, "America/Chicago")
        assert result == value.to_pydatetime()

    def test_invalid_timezone_raises(self):
        with pytest.raises(ZoneInfoNotFoundError):
            localize_collectiontime(datetime(2026, 1, 15), "Not/AZone")

    def test_non_datetime_value_passes_through(self):
        # pandas NaN edge cases should not crash the upload path.
        result = localize_collectiontime(float("nan"), "UTC")
        assert result is not None and result != result  # NaN stays NaN

    def test_dst_ambiguous_time_resolves_to_earlier_offset(self):
        # 2026-11-01 01:30 CST/CDT is ambiguous; fold=0 picks CDT (UTC-5).
        value = datetime(2026, 11, 1, 1, 30, 0)
        result = localize_collectiontime(value, "America/Chicago")
        assert result.utcoffset().total_seconds() == -5 * 3600
