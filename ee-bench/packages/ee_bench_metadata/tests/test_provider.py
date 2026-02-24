"""Tests for MetadataProvider."""

from __future__ import annotations

import pytest

from ee_bench_generator.errors import ProviderError
from ee_bench_generator.metadata import Context, Selection
from ee_bench_metadata.provider import MetadataProvider, parse_metadata_block

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_BODY = """\
## Problem Statement

Some problem description.

## Hints

Some hints.

<!--METADATA
instance_id:protonmail__webclients__42
repo:protonmail/webclients
base_commit:abc123def456
version:1.0
FAIL_TO_PASS:["test_foo", "test_bar"]
PASS_TO_PASS:["test_baz"]
repo_language:TypeScript
METADATA-->
"""

BODY_NO_METADATA = """\
## Problem Statement

Just a body with no metadata block.
"""

BODY_ESCAPED_NEWLINES = """\
<!--METADATA
multi_line:line1\\nline2\\nline3
simple:value
METADATA-->
"""


def _make_context(text: str = "") -> Context:
    return Context(
        selection=Selection(resource="pull_requests", filters={}),
        current_item={"text": text},
    )


# ---------------------------------------------------------------------------
# parse_metadata_block unit tests
# ---------------------------------------------------------------------------


class TestParseMetadataBlock:
    def test_parse_sample(self) -> None:
        result = parse_metadata_block(SAMPLE_BODY)
        assert result["instance_id"] == "protonmail__webclients__42"
        assert result["repo"] == "protonmail/webclients"
        assert result["base_commit"] == "abc123def456"
        assert result["version"] == "1.0"
        assert result["FAIL_TO_PASS"] == '["test_foo", "test_bar"]'
        assert result["PASS_TO_PASS"] == '["test_baz"]'
        assert result["repo_language"] == "TypeScript"

    def test_no_metadata_block(self) -> None:
        assert parse_metadata_block(BODY_NO_METADATA) == {}

    def test_empty_string(self) -> None:
        assert parse_metadata_block("") == {}

    def test_escaped_newlines_restored(self) -> None:
        result = parse_metadata_block(BODY_ESCAPED_NEWLINES)
        assert result["multi_line"] == "line1\nline2\nline3"
        assert result["simple"] == "value"

    def test_colon_in_value(self) -> None:
        body = "<!--METADATA\nurl:https://example.com\nMETADATA-->"
        result = parse_metadata_block(body)
        assert result["url"] == "https://example.com"


# ---------------------------------------------------------------------------
# MetadataProvider unit tests
# ---------------------------------------------------------------------------


class TestMetadataProvider:
    def setup_method(self) -> None:
        self.provider = MetadataProvider()

    def test_prepare_sets_fields(self) -> None:
        self.provider.prepare(fields=["instance_id", "repo"])
        meta = self.provider.metadata
        assert meta.can_provide("instance_id", "pull_request")
        assert meta.can_provide("repo", "pull_request")

    def test_prepare_custom_source(self) -> None:
        self.provider.prepare(fields=["instance_id"], source="issue")
        meta = self.provider.metadata
        assert meta.can_provide("instance_id", "issue")
        assert not meta.can_provide("instance_id", "pull_request")

    def test_prepare_requires_fields(self) -> None:
        with pytest.raises(ProviderError, match="requires 'fields'"):
            self.provider.prepare()

    def test_prepare_empty_fields_raises(self) -> None:
        with pytest.raises(ProviderError, match="requires 'fields'"):
            self.provider.prepare(fields=[])

    def test_metadata_name(self) -> None:
        self.provider.prepare(fields=["instance_id"])
        assert self.provider.metadata.name == "metadata"

    def test_metadata_default_source(self) -> None:
        self.provider.prepare(fields=["instance_id"])
        assert self.provider.metadata.sources == ["pull_request"]

    def test_metadata_no_fields_before_prepare(self) -> None:
        assert self.provider.metadata.provided_fields == []

    def test_iter_items_raises(self) -> None:
        self.provider.prepare(fields=["instance_id"])
        ctx = _make_context()
        with pytest.raises(ProviderError, match="enrichment-only"):
            list(self.provider.iter_items(ctx))

    def test_get_field_extracts_metadata(self) -> None:
        self.provider.prepare(fields=["instance_id", "repo", "base_commit"])
        ctx = _make_context(SAMPLE_BODY)
        assert self.provider.get_field("instance_id", "pull_request", ctx) == "protonmail__webclients__42"
        assert self.provider.get_field("repo", "pull_request", ctx) == "protonmail/webclients"
        assert self.provider.get_field("base_commit", "pull_request", ctx) == "abc123def456"

    def test_get_field_missing_returns_empty(self) -> None:
        self.provider.prepare(fields=["nonexistent_field"])
        ctx = _make_context(SAMPLE_BODY)
        assert self.provider.get_field("nonexistent_field", "pull_request", ctx) == ""

    def test_get_field_unlisted_raises(self) -> None:
        self.provider.prepare(fields=["instance_id"])
        ctx = _make_context(SAMPLE_BODY)
        with pytest.raises(ProviderError, match="does not provide"):
            self.provider.get_field("repo", "pull_request", ctx)

    def test_get_field_no_metadata_block(self) -> None:
        self.provider.prepare(fields=["instance_id"])
        ctx = _make_context(BODY_NO_METADATA)
        assert self.provider.get_field("instance_id", "pull_request", ctx) == ""

    def test_get_field_empty_text(self) -> None:
        self.provider.prepare(fields=["instance_id"])
        ctx = _make_context("")
        assert self.provider.get_field("instance_id", "pull_request", ctx) == ""

    def test_get_field_no_current_item(self) -> None:
        self.provider.prepare(fields=["instance_id"])
        ctx = Context(
            selection=Selection(resource="pull_requests", filters={}),
            current_item=None,
        )
        assert self.provider.get_field("instance_id", "pull_request", ctx) == ""

    def test_caching_same_text(self) -> None:
        """Verify that parsing is cached per text value."""
        self.provider.prepare(fields=["instance_id", "repo"])
        ctx = _make_context(SAMPLE_BODY)
        # First call parses
        self.provider.get_field("instance_id", "pull_request", ctx)
        # Second call uses cache
        result = self.provider.get_field("repo", "pull_request", ctx)
        assert result == "protonmail/webclients"
        # Verify cache key is set
        assert self.provider._cache_key == SAMPLE_BODY

    def test_caching_different_text(self) -> None:
        """Verify cache is invalidated when text changes."""
        self.provider.prepare(fields=["instance_id"])
        ctx1 = _make_context(SAMPLE_BODY)
        self.provider.get_field("instance_id", "pull_request", ctx1)

        other_body = "<!--METADATA\ninstance_id:other__id__99\nMETADATA-->"
        ctx2 = _make_context(other_body)
        result = self.provider.get_field("instance_id", "pull_request", ctx2)
        assert result == "other__id__99"


# ---------------------------------------------------------------------------
# MetadataProvider auto-discovery mode tests
# ---------------------------------------------------------------------------


class TestMetadataProviderAutoDiscovery:
    def setup_method(self) -> None:
        self.provider = MetadataProvider()

    def test_prepare_auto_mode(self) -> None:
        self.provider.prepare(fields="auto")
        assert self.provider._auto_discover is True
        assert self.provider._fields == []

    def test_prepare_star_mode(self) -> None:
        self.provider.prepare(fields="*")
        assert self.provider._auto_discover is True

    def test_auto_mode_metadata_has_wildcard_flag(self) -> None:
        self.provider.prepare(fields="auto")
        assert self.provider.metadata.wildcard is True
        assert self.provider.metadata.provided_fields == []

    def test_auto_mode_can_provide_any_field(self) -> None:
        self.provider.prepare(fields="auto")
        meta = self.provider.metadata
        assert meta.can_provide("anything", "pull_request")
        assert meta.can_provide("nonexistent_field", "")

    def test_auto_mode_get_field_returns_parsed_values(self) -> None:
        self.provider.prepare(fields="auto")
        ctx = _make_context(SAMPLE_BODY)
        assert self.provider.get_field("instance_id", "pull_request", ctx) == "protonmail__webclients__42"
        assert self.provider.get_field("repo", "pull_request", ctx) == "protonmail/webclients"
        assert self.provider.get_field("version", "pull_request", ctx) == "1.0"

    def test_auto_mode_get_field_missing_key_returns_empty(self) -> None:
        self.provider.prepare(fields="auto")
        ctx = _make_context(SAMPLE_BODY)
        assert self.provider.get_field("nonexistent_key", "pull_request", ctx) == ""

    def test_auto_mode_get_field_no_metadata_block(self) -> None:
        self.provider.prepare(fields="auto")
        ctx = _make_context(BODY_NO_METADATA)
        assert self.provider.get_field("any_field", "pull_request", ctx) == ""

    def test_get_discovered_field_names_after_parsing(self) -> None:
        self.provider.prepare(fields="auto")
        ctx = _make_context(SAMPLE_BODY)
        # Trigger parsing
        self.provider.get_field("instance_id", "pull_request", ctx)
        discovered = self.provider.get_discovered_field_names()
        assert discovered == {
            "instance_id", "repo", "base_commit", "version",
            "FAIL_TO_PASS", "PASS_TO_PASS", "repo_language",
        }

    def test_get_discovered_field_names_before_parsing(self) -> None:
        self.provider.prepare(fields="auto")
        assert self.provider.get_discovered_field_names() == set()

    def test_explicit_mode_no_wildcard(self) -> None:
        self.provider.prepare(fields=["instance_id", "repo"])
        assert self.provider.metadata.wildcard is False

    def test_explicit_mode_get_discovered_field_names(self) -> None:
        """get_discovered_field_names works in explicit mode too."""
        self.provider.prepare(fields=["instance_id"])
        ctx = _make_context(SAMPLE_BODY)
        self.provider.get_field("instance_id", "pull_request", ctx)
        # Returns all parsed keys, not just configured fields
        discovered = self.provider.get_discovered_field_names()
        assert "instance_id" in discovered
        assert "repo" in discovered
