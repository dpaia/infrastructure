"""Tests for clock utilities."""

import re
from datetime import datetime, timezone

import pytest

from ee_bench_generator.clock import now_iso8601_utc


class TestNowIso8601Utc:
    """Tests for now_iso8601_utc function."""

    def test_returns_string(self):
        """Test that now_iso8601_utc returns a string."""
        result = now_iso8601_utc()
        assert isinstance(result, str)

    def test_returns_iso8601_format(self):
        """Test that the result is in ISO 8601 format."""
        result = now_iso8601_utc()

        # ISO 8601 pattern with timezone
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+00:00$"
        assert re.match(pattern, result), f"'{result}' is not valid ISO 8601 format"

    def test_has_utc_timezone_suffix(self):
        """Test that the result has +00:00 timezone suffix."""
        result = now_iso8601_utc()
        assert result.endswith("+00:00"), f"'{result}' should end with +00:00"

    def test_returns_current_time(self):
        """Test that the result is close to current time."""
        before = datetime.now(timezone.utc)
        result = now_iso8601_utc()
        after = datetime.now(timezone.utc)

        # Parse the result
        parsed = datetime.fromisoformat(result)

        # Should be between before and after
        assert before <= parsed <= after

    def test_parseable_by_datetime(self):
        """Test that the result can be parsed by datetime.fromisoformat."""
        result = now_iso8601_utc()

        # Should not raise
        parsed = datetime.fromisoformat(result)

        assert parsed.tzinfo is not None
        assert parsed.tzinfo.utcoffset(None).total_seconds() == 0
