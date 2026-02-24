"""Tests for SectionProvider."""

from __future__ import annotations

import pytest

from ee_bench_generator.errors import ProviderError
from ee_bench_generator.metadata import Context, Selection
from ee_bench_metadata.section_provider import SectionProvider, _parse_sections

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_BODY = """\
## Problem Statement

Some problem description.
With multiple lines.

## Hints

Some hints here.

## Requirements

- Requirement 1
- Requirement 2

## Interface

```python
def foo(bar: int) -> str:
    pass
```

<!--METADATA
instance_id:protonmail__webclients__42
repo:protonmail/webclients
METADATA-->
"""

BODY_NO_SECTIONS = """\
Just a body with no markdown sections at all.
"""

BODY_PARTIAL_SECTIONS = """\
## Problem Statement

Only problem statement here.

<!--METADATA
instance_id:test__repo__1
METADATA-->
"""


def _make_context(text: str = "") -> Context:
    return Context(
        selection=Selection(resource="pull_requests", filters={}),
        current_item={"text": text},
    )


# ---------------------------------------------------------------------------
# _parse_sections unit tests
# ---------------------------------------------------------------------------


class TestParseSections:
    def test_extracts_all_sections(self) -> None:
        sections = {
            "problem_statement": "## Problem Statement",
            "hints_text": "## Hints",
            "requirements": "## Requirements",
            "interface": "## Interface",
        }
        result = _parse_sections(SAMPLE_BODY, sections)
        assert "Some problem description." in result["problem_statement"]
        assert "With multiple lines." in result["problem_statement"]
        assert "Some hints here." in result["hints_text"]
        assert "- Requirement 1" in result["requirements"]
        assert "def foo(bar: int)" in result["interface"]

    def test_missing_section_returns_empty(self) -> None:
        sections = {"nonexistent": "## Nonexistent Section"}
        result = _parse_sections(SAMPLE_BODY, sections)
        assert result["nonexistent"] == ""

    def test_no_sections_in_text(self) -> None:
        sections = {"problem_statement": "## Problem Statement"}
        result = _parse_sections(BODY_NO_SECTIONS, sections)
        assert result["problem_statement"] == ""

    def test_empty_text(self) -> None:
        sections = {"problem_statement": "## Problem Statement"}
        result = _parse_sections("", sections)
        assert result["problem_statement"] == ""

    def test_strips_metadata_block_from_last_section(self) -> None:
        sections = {"problem_statement": "## Problem Statement"}
        result = _parse_sections(BODY_PARTIAL_SECTIONS, sections)
        assert "METADATA" not in result["problem_statement"]
        assert "Only problem statement here." in result["problem_statement"]

    def test_consecutive_sections_have_correct_boundaries(self) -> None:
        sections = {
            "problem_statement": "## Problem Statement",
            "hints_text": "## Hints",
        }
        result = _parse_sections(SAMPLE_BODY, sections)
        # problem_statement should NOT contain hints content
        assert "Some hints here." not in result["problem_statement"]
        # hints should NOT contain requirements content
        assert "Requirement" not in result["hints_text"]

    def test_empty_sections_dict(self) -> None:
        result = _parse_sections(SAMPLE_BODY, {})
        assert result == {}


# ---------------------------------------------------------------------------
# SectionProvider unit tests
# ---------------------------------------------------------------------------


class TestSectionProvider:
    def setup_method(self) -> None:
        self.provider = SectionProvider()

    def test_prepare_sets_sections(self) -> None:
        self.provider.prepare(sections={
            "problem_statement": "## Problem Statement",
            "hints_text": "## Hints",
        })
        meta = self.provider.metadata
        assert meta.can_provide("problem_statement", "pull_request")
        assert meta.can_provide("hints_text", "pull_request")

    def test_prepare_custom_source(self) -> None:
        self.provider.prepare(
            sections={"problem_statement": "## Problem Statement"},
            source="issue",
        )
        meta = self.provider.metadata
        assert meta.can_provide("problem_statement", "issue")
        assert not meta.can_provide("problem_statement", "pull_request")

    def test_prepare_requires_sections(self) -> None:
        with pytest.raises(ProviderError, match="requires 'sections'"):
            self.provider.prepare()

    def test_prepare_empty_sections_raises(self) -> None:
        with pytest.raises(ProviderError, match="requires 'sections'"):
            self.provider.prepare(sections={})

    def test_metadata_name(self) -> None:
        self.provider.prepare(sections={"ps": "## PS"})
        assert self.provider.metadata.name == "markdown_sections"

    def test_metadata_default_source(self) -> None:
        self.provider.prepare(sections={"ps": "## PS"})
        assert self.provider.metadata.sources == ["pull_request"]

    def test_metadata_no_fields_before_prepare(self) -> None:
        assert self.provider.metadata.provided_fields == []

    def test_iter_items_raises(self) -> None:
        self.provider.prepare(sections={"ps": "## PS"})
        ctx = _make_context()
        with pytest.raises(ProviderError, match="enrichment-only"):
            list(self.provider.iter_items(ctx))

    def test_get_field_extracts_section(self) -> None:
        self.provider.prepare(sections={
            "problem_statement": "## Problem Statement",
            "hints_text": "## Hints",
        })
        ctx = _make_context(SAMPLE_BODY)
        ps = self.provider.get_field("problem_statement", "pull_request", ctx)
        assert "Some problem description." in ps
        hints = self.provider.get_field("hints_text", "pull_request", ctx)
        assert "Some hints here." in hints

    def test_get_field_missing_section_returns_empty(self) -> None:
        self.provider.prepare(sections={
            "nonexistent": "## Nonexistent",
        })
        ctx = _make_context(SAMPLE_BODY)
        assert self.provider.get_field("nonexistent", "pull_request", ctx) == ""

    def test_get_field_unlisted_raises(self) -> None:
        self.provider.prepare(sections={
            "problem_statement": "## Problem Statement",
        })
        ctx = _make_context(SAMPLE_BODY)
        with pytest.raises(ProviderError, match="does not provide"):
            self.provider.get_field("hints_text", "pull_request", ctx)

    def test_get_field_no_current_item(self) -> None:
        self.provider.prepare(sections={
            "problem_statement": "## Problem Statement",
        })
        ctx = Context(
            selection=Selection(resource="pull_requests", filters={}),
            current_item=None,
        )
        assert self.provider.get_field("problem_statement", "pull_request", ctx) == ""

    def test_caching_same_text(self) -> None:
        """Verify that parsing is cached per text value."""
        self.provider.prepare(sections={
            "problem_statement": "## Problem Statement",
            "hints_text": "## Hints",
        })
        ctx = _make_context(SAMPLE_BODY)
        self.provider.get_field("problem_statement", "pull_request", ctx)
        result = self.provider.get_field("hints_text", "pull_request", ctx)
        assert "Some hints here." in result
        assert self.provider._cache_key == SAMPLE_BODY

    def test_caching_different_text(self) -> None:
        """Verify cache is invalidated when text changes."""
        self.provider.prepare(sections={
            "problem_statement": "## Problem Statement",
        })
        ctx1 = _make_context(SAMPLE_BODY)
        self.provider.get_field("problem_statement", "pull_request", ctx1)

        other_body = "## Problem Statement\n\nDifferent problem.\n"
        ctx2 = _make_context(other_body)
        result = self.provider.get_field("problem_statement", "pull_request", ctx2)
        assert result == "Different problem."
