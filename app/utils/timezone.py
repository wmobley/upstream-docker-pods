"""Timezone helpers for measurement collection times.

The Upstream platform stores measurement ``collectiontime`` values as aware
``TIMESTAMPTZ`` instants. CSV uploads and single-measurement writes may send
naive local timestamps; those are interpreted in the station's declared IANA
timezone (``stations.timezone``). Already-aware values pass through unchanged.

**Accepted timestamp formats:**
- ISO-8601 (preferred, fastest):
  - Date only: ``YYYY-MM-DD`` (e.g., ``2024-01-01``)
  - Date + time: ``YYYY-MM-DD HH:MM:SS`` or ``YYYY-MM-DDTHH:MM:SS`` (e.g., ``2024-01-01 12:00:00``)
  - With timezone: optionally ``Z`` (UTC) or ``+HH:MM``/``-HH:MM`` offset (e.g., ``2024-01-01T12:00:00Z``, ``2024-01-01 12:00:00-05:00``)
- US common formats (24-hour clock):
  - ``M/D/YY HH:MM`` (e.g., ``8/6/26 17:15``)
  - ``M/D/YYYY HH:MM`` (e.g., ``8/6/2026 17:15``)
  - ``MM/DD/YY HH:MM`` (e.g., ``08/06/26 17:15``)
  - ``MM/DD/YYYY HH:MM`` (e.g., ``08/06/2026 17:15``)
  - With seconds: ``M/D/YY HH:MM:SS``, ``M/D/YYYY HH:MM:SS``, etc.
- European common formats (24-hour clock):
  - ``D/M/YY HH:MM`` (e.g., ``6/8/26 17:15``)
  - ``D/M/YYYY HH:MM`` (e.g., ``6/8/2026 17:15``)
  - ``DD/MM/YY HH:MM`` (e.g., ``06/08/26 17:15``)
  - ``DD/MM/YYYY HH:MM`` (e.g., ``06/08/2026 17:15``)
  - With seconds: ``D/M/YY HH:MM:SS``, etc.
- Y/M/D formats (24-hour clock):
  - ``YYYY/MM/DD HH:MM`` (e.g., ``2026/08/06 17:15``)
  - ``YYYY/MM/DD HH:MM:SS`` (e.g., ``2026/08/06 17:15:00``)

Note: 12-hour format with AM/PM is **not** supported.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

# Common non-ISO datetime formats to try (in order of likelihood).
# Using 24-hour clock only (no AM/PM support).
_DATETIME_FORMATS: tuple[str, ...] = (
    # US formats (month/day/year)
    "%m/%d/%y %H:%M",
    "%m/%d/%Y %H:%M",
    "%m/%d/%y %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    # European formats (day/month/year)
    "%d/%m/%y %H:%M",
    "%d/%m/%Y %H:%M",
    "%d/%m/%y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    # Y/M/D formats (year/month/day with slashes) - common in some systems
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    # Additional common variants
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
)


def _parse_datetime_string(value: str) -> datetime:
    """Parse a datetime string trying multiple formats.

    Tries ISO format first (fast C implementation), then falls back to
    common non-ISO formats using strptime.
    """
    # Fast path: ISO 8601 (handled by C implementation)
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass

    # Fallback: try common formats
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    # If all formats fail, raise a descriptive error
    raise ValueError(
        f"Invalid datetime string: '{value}'. "
        f"Supported formats: ISO 8601 (YYYY-MM-DDTHH:MM:SS), "
        f"US (M/D/YY HH:MM), European (D/M/YY HH:MM), Y/M/D (YYYY/MM/DD HH:MM), and variants with/without seconds."
    )


def localize_collectiontime(value: datetime | str, timezone: str) -> datetime:
    """Return an aware datetime for a ``collectiontime`` value.

    Naive values are interpreted in the station's declared IANA ``timezone``;
    already-aware values pass through unchanged. ``value`` may be a
    ``datetime``, a pandas ``Timestamp`` (a ``datetime`` subclass), or a
    string in one of the supported formats.

    DST-ambiguous local times (the fall-back hour) resolve to the earlier
    offset (``fold=0``), matching ``ZoneInfo``'s default behavior.
    """
    if isinstance(value, str):
        value = _parse_datetime_string(value)
    elif not isinstance(value, datetime):
        # Non-datetime values (e.g. pandas NaN edge cases) pass through
        # unchanged so callers keep their previous behavior.
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=ZoneInfo(timezone))
    return value
