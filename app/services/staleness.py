"""Decide whether a station has stopped reporting.

A station is stale when its newest measurement is older than three expected
reporting intervals (``expected_interval_minutes`` in the station metadata,
defaulting to 48 hours). Silence is only a problem while the parent campaign's
IOP window is open: before ``start_date`` or after ``end_date`` a station is
never stale. The UI applies the same rule to individual stations
(``upstream-ui/src/utils/staleness.ts``); keep the two in sync.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

EXPECTED_INTERVAL_METADATA_KEY = "expected_interval_minutes"
MISSED_INTERVALS_BEFORE_STALE = 3
DEFAULT_STALE_AFTER = timedelta(hours=48)


def _as_utc(value: datetime) -> datetime:
    """Treat naive datetimes as UTC so they compare with aware ones."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def expected_interval_minutes(metadata: Mapping[str, Any] | None) -> float | None:
    raw = (metadata or {}).get(EXPECTED_INTERVAL_METADATA_KEY)
    if isinstance(raw, bool):
        return None
    try:
        minutes = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return minutes if minutes > 0 else None


def stale_after(metadata: Mapping[str, Any] | None) -> timedelta:
    minutes = expected_interval_minutes(metadata)
    if minutes is None:
        return DEFAULT_STALE_AFTER
    return timedelta(minutes=minutes * MISSED_INTERVALS_BEFORE_STALE)


def is_station_stale(
    last_measurement_time: datetime | None,
    station_metadata: Mapping[str, Any] | None,
    campaign_start: datetime | None,
    campaign_end: datetime | None,
    now: datetime | None = None,
) -> bool:
    """True when an active-IOP station has gone quiet for too long.

    A station with no measurements at all is not reported as stale: there is
    no "last update" to have gone out of date, and the UI shows "No data yet".
    """
    if last_measurement_time is None:
        return False
    current = _as_utc(now) if now else datetime.now(timezone.utc)
    if campaign_end is not None and current > _as_utc(campaign_end):
        return False
    if campaign_start is not None and current < _as_utc(campaign_start):
        return False
    return current - _as_utc(last_measurement_time) > stale_after(station_metadata)
