"""Timezone helpers for measurement collection times.

The Upstream platform stores measurement ``collectiontime`` values as aware
``TIMESTAMPTZ`` instants. CSV uploads and single-measurement writes may send
naive local timestamps; those are interpreted in the station's declared IANA
timezone (``stations.timezone``). Already-aware values pass through unchanged.

**Accepted timestamp format (ISO-8601):**
- Date only: ``YYYY-MM-DD`` (e.g., ``2024-01-01``)
- Date + time: ``YYYY-MM-DD HH:MM:SS`` or ``YYYY-MM-DDTHH:MM:SS`` (e.g., ``2024-01-01 12:00:00``)
- With timezone: optionally ``Z`` (UTC) or ``+HH:MM``/``-HH:MM`` offset (e.g., ``2024-01-01T12:00:00Z``, ``2024-01-01 12:00:00-05:00``)

Note: 12-hour format with AM/PM is **not** supported.
"""

from datetime import datetime
from zoneinfo import ZoneInfo


def localize_collectiontime(value: datetime | str, timezone: str) -> datetime:
    """Return an aware datetime for a ``collectiontime`` value.

    Naive values are interpreted in the station's declared IANA ``timezone``;
    already-aware values pass through unchanged. ``value`` may be a
    ``datetime``, a pandas ``Timestamp`` (a ``datetime`` subclass), or an
    ISO-8601 string.

    DST-ambiguous local times (the fall-back hour) resolve to the earlier
    offset (``fold=0``), matching ``ZoneInfo``'s default behavior.
    """
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    elif not isinstance(value, datetime):
        # Non-datetime values (e.g. pandas NaN edge cases) pass through
        # unchanged so callers keep their previous behavior.
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=ZoneInfo(timezone))
    return value
