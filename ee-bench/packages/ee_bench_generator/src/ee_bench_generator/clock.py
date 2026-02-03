"""Clock utilities for timestamp generation."""

from datetime import datetime, timezone


def now_iso8601_utc() -> str:
    """Return the current UTC time as an ISO 8601 string with +00:00 suffix.

    Returns:
        ISO 8601 formatted timestamp string with explicit +00:00 timezone.

    Example:
        >>> now_iso8601_utc()  # doctest: +SKIP
        '2024-01-15T10:30:45.123456+00:00'
    """
    return datetime.now(timezone.utc).isoformat()
