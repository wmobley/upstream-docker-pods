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

    # --- New format support tests ---

    def test_us_format_m_d_yy_h_m(self):
        # US format: M/D/YY HH:MM (e.g., 8/6/26 17:15)
        result = localize_collectiontime("8/6/26 17:15", "America/Chicago")
        assert result.isoformat() == "2026-08-06T17:15:00-05:00"

    def test_us_format_m_d_yyyy_h_m(self):
        # US format: M/D/YYYY HH:MM (e.g., 8/6/2026 17:15)
        result = localize_collectiontime("8/6/2026 17:15", "America/Chicago")
        assert result.isoformat() == "2026-08-06T17:15:00-05:00"

    def test_us_format_mm_dd_yy_h_m(self):
        # US format: MM/DD/YY HH:MM (e.g., 08/06/26 17:15)
        result = localize_collectiontime("08/06/26 17:15", "America/Chicago")
        assert result.isoformat() == "2026-08-06T17:15:00-05:00"

    def test_us_format_mm_dd_yyyy_h_m(self):
        # US format: MM/DD/YYYY HH:MM (e.g., 08/06/2026 17:15)
        result = localize_collectiontime("08/06/2026 17:15", "America/Chicago")
        assert result.isoformat() == "2026-08-06T17:15:00-05:00"

    def test_us_format_with_seconds(self):
        # US format with seconds: M/D/YY HH:MM:SS
        result = localize_collectiontime("8/6/26 17:15:30", "America/Chicago")
        assert result.isoformat() == "2026-08-06T17:15:30-05:00"

    def test_european_format_d_m_yy_h_m(self):
        # European format: D/M/YY HH:MM (e.g., 13/8/26 17:15 = 13 Aug 2026)
        # Using day=13 makes it unambiguous (US format would reject month=13)
        result = localize_collectiontime("13/8/26 17:15", "Europe/London")
        assert result.isoformat() == "2026-08-13T17:15:00+01:00"

    def test_european_format_d_m_yyyy_h_m(self):
        # European format: D/M/YYYY HH:MM (unambiguous with day > 12)
        result = localize_collectiontime("13/8/2026 17:15", "Europe/London")
        assert result.isoformat() == "2026-08-13T17:15:00+01:00"

    def test_european_format_dd_mm_yy_h_m(self):
        # European format: DD/MM/YY HH:MM (unambiguous with day > 12)
        result = localize_collectiontime("13/08/26 17:15", "Europe/London")
        assert result.isoformat() == "2026-08-13T17:15:00+01:00"

    def test_european_format_with_seconds(self):
        # European format with seconds (unambiguous day > 12)
        result = localize_collectiontime("13/8/26 17:15:30", "Europe/London")
        assert result.isoformat() == "2026-08-13T17:15:30+01:00"

    def test_iso_format_with_space_and_seconds(self):
        # ISO-like with space separator and seconds
        result = localize_collectiontime("2026-08-06 17:15:30", "America/Chicago")
        assert result.isoformat() == "2026-08-06T17:15:30-05:00"

    def test_iso_format_with_space_no_seconds(self):
        # ISO-like with space separator, no seconds
        result = localize_collectiontime("2026-08-06 17:15", "America/Chicago")
        assert result.isoformat() == "2026-08-06T17:15:00-05:00"

    def test_invalid_format_raises_clear_error(self):
        with pytest.raises(ValueError, match="Invalid datetime string"):
            localize_collectiontime("not-a-date", "UTC")

    def test_12_hour_format_not_supported(self):
        # 12-hour format with AM/PM is explicitly not supported
        with pytest.raises(ValueError, match="Invalid datetime string"):
            localize_collectiontime("8/6/26 5:15 PM", "UTC")
