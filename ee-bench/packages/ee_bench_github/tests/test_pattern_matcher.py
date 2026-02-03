"""Tests for pattern matching utilities."""

import pytest

from ee_bench_github.pattern_matcher import (
    expand_repo_pattern,
    is_pattern,
    match_pattern,
)


class TestIsPattern:
    """Tests for is_pattern function."""

    def test_no_wildcards(self):
        """Test string without wildcards."""
        assert not is_pattern("apache/kafka")

    def test_asterisk_wildcard(self):
        """Test string with asterisk."""
        assert is_pattern("apache/*")
        assert is_pattern("apache/kafka-*")
        assert is_pattern("*")

    def test_question_wildcard(self):
        """Test string with question mark."""
        assert is_pattern("apache/kafka-?")
        assert is_pattern("?")

    def test_combined_wildcards(self):
        """Test string with both wildcards."""
        assert is_pattern("apache/kafka-*-?")


class TestMatchPattern:
    """Tests for match_pattern function."""

    def test_match_all(self):
        """Test matching all with *."""
        values = ["kafka", "flink", "spark"]
        assert match_pattern("*", values) == values

    def test_match_prefix(self):
        """Test matching by prefix."""
        values = ["kafka-clients", "kafka-streams", "flink", "spark"]
        result = match_pattern("kafka-*", values)
        assert result == ["kafka-clients", "kafka-streams"]

    def test_match_suffix(self):
        """Test matching by suffix."""
        values = ["kafka-core", "flink-core", "spark-core"]
        result = match_pattern("*-core", values)
        assert result == ["kafka-core", "flink-core", "spark-core"]

    def test_match_single_char(self):
        """Test matching single character with ?."""
        values = ["v1", "v2", "v10", "a1"]
        result = match_pattern("v?", values)
        assert result == ["v1", "v2"]

    def test_no_matches(self):
        """Test when nothing matches."""
        values = ["kafka", "flink"]
        result = match_pattern("spark*", values)
        assert result == []

    def test_empty_values(self):
        """Test with empty values list."""
        result = match_pattern("*", [])
        assert result == []


class TestExpandRepoPattern:
    """Tests for expand_repo_pattern function."""

    def test_expand_all_repos(self):
        """Test expanding * to all repos."""

        def mock_get_repos(owner):
            assert owner == "apache"
            return iter([{"name": "kafka"}, {"name": "flink"}, {"name": "spark"}])

        result = expand_repo_pattern("apache/*", mock_get_repos)
        assert result == ["apache/kafka", "apache/flink", "apache/spark"]

    def test_expand_with_prefix(self):
        """Test expanding pattern with prefix."""

        def mock_get_repos(owner):
            return iter(
                [
                    {"name": "kafka"},
                    {"name": "kafka-clients"},
                    {"name": "kafka-streams"},
                    {"name": "flink"},
                ]
            )

        result = expand_repo_pattern("apache/kafka*", mock_get_repos)
        assert result == [
            "apache/kafka",
            "apache/kafka-clients",
            "apache/kafka-streams",
        ]

    def test_expand_no_matches(self):
        """Test expanding pattern with no matches."""

        def mock_get_repos(owner):
            return iter([{"name": "flink"}, {"name": "spark"}])

        result = expand_repo_pattern("apache/kafka*", mock_get_repos)
        assert result == []

    def test_expand_with_full_name(self):
        """Test expanding when repos have full_name field."""

        def mock_get_repos(owner):
            return iter([{"full_name": "apache/kafka"}, {"full_name": "apache/flink"}])

        result = expand_repo_pattern("apache/*", mock_get_repos)
        assert result == ["apache/kafka", "apache/flink"]

    def test_invalid_pattern_no_slash(self):
        """Test that pattern without / raises error."""

        def mock_get_repos(owner):
            return iter([])

        with pytest.raises(ValueError, match="owner/repo"):
            expand_repo_pattern("kafka*", mock_get_repos)

    def test_wildcard_in_owner_raises(self):
        """Test that wildcard in owner part raises error."""

        def mock_get_repos(owner):
            return iter([])

        with pytest.raises(ValueError, match="not supported"):
            expand_repo_pattern("apache*/kafka", mock_get_repos)

    def test_question_mark_pattern(self):
        """Test expanding with ? wildcard."""

        def mock_get_repos(owner):
            return iter([{"name": "v1"}, {"name": "v2"}, {"name": "v10"}])

        result = expand_repo_pattern("owner/v?", mock_get_repos)
        assert result == ["owner/v1", "owner/v2"]
