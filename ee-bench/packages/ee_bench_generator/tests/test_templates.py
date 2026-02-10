"""Tests for ee_bench_generator.templates — generic Jinja2 rendering."""

from __future__ import annotations

import pytest

from ee_bench_generator.templates import (
    MAX_GH_TITLE_LEN,
    _first_sentence,
    _truncate_title,
    render_template,
)


class TestFirstSentence:
    def test_period_followed_by_space(self):
        assert _first_sentence("Fix the bug. More details here.") == "Fix the bug."

    def test_period_followed_by_newline(self):
        assert _first_sentence("Fix the bug.\nMore details") == "Fix the bug."

    def test_no_period_takes_first_line(self):
        assert _first_sentence("Fix the bug\nMore details") == "Fix the bug"

    def test_single_sentence_no_trailing_space(self):
        assert _first_sentence("Fix the bug") == "Fix the bug"

    def test_empty_string(self):
        assert _first_sentence("") == ""


class TestTruncateTitle:
    def test_short_text_unchanged(self):
        assert _truncate_title("Short title") == "Short title"

    def test_long_text_truncated(self):
        long_text = "A" * 300
        result = _truncate_title(long_text)
        assert len(result) == MAX_GH_TITLE_LEN
        assert result.endswith("...")

    def test_exact_length_unchanged(self):
        exact = "A" * MAX_GH_TITLE_LEN
        assert _truncate_title(exact) == exact

    def test_strips_whitespace(self):
        assert _truncate_title("  hello  ") == "hello"


class TestRenderTemplate:
    def test_basic_variable_substitution(self):
        result = render_template("Hello {{ name }}", {"name": "World"})
        assert result == "Hello World"

    def test_missing_variable_renders_empty(self):
        result = render_template("Value: {{ missing }}", {})
        assert result == "Value: "

    def test_default_filter(self):
        result = render_template('{{ missing | default("fallback") }}', {})
        assert result == "fallback"

    def test_first_sentence_filter(self):
        result = render_template(
            "{{ text | first_sentence }}",
            {"text": "Fix bug. Details here."},
        )
        assert result == "Fix bug."

    def test_truncate_title_filter(self):
        result = render_template(
            "{{ text | truncate_title }}",
            {"text": "A" * 300},
        )
        assert len(result) == MAX_GH_TITLE_LEN

    def test_chained_filters(self):
        result = render_template(
            "{{ text | first_sentence | truncate_title }}",
            {"text": "Short sentence. More."},
        )
        assert result == "Short sentence."

    def test_extra_filters(self):
        result = render_template(
            "{{ name | shout }}",
            {"name": "hello"},
            extra_filters={"shout": lambda s: s.upper()},
        )
        assert result == "HELLO"

    def test_extra_globals(self):
        def greet(name: str) -> str:
            return f"Hi, {name}!"

        result = render_template(
            "{{ greet(name) }}",
            {"name": "Alice"},
            extra_globals={"greet": greet},
        )
        assert result == "Hi, Alice!"

    def test_conditional_rendering(self):
        template = "{% if show %}visible{% endif %}"
        assert render_template(template, {"show": True}) == "visible"
        assert render_template(template, {"show": False}) == ""

    def test_keep_trailing_newline(self):
        result = render_template("hello\n", {})
        assert result == "hello\n"
