"""Tests for PR body building and metadata parsing."""

from __future__ import annotations

import pytest

from ee_bench_importer.pr_body import (
    build_metadata_block,
    build_pr_body,
    parse_metadata_block,
    render_pr_body_template,
    render_pr_title_template,
    resolve_metadata_fields,
    update_metadata_in_body,
)


class TestBuildPrBody:
    def test_basic_body(self):
        body = build_pr_body("Fix the bug in module X")
        assert "## Problem Statement" in body
        assert "Fix the bug in module X" in body

    def test_body_with_hints(self):
        body = build_pr_body("Fix bug", hints_text="Check module Y")
        assert "## Hints" in body
        assert "Check module Y" in body

    def test_body_with_metadata(self):
        metadata = {"instance_id": "test__repo-42", "version": "1.0"}
        body = build_pr_body("Fix bug", metadata=metadata)
        assert "<!--METADATA" in body
        assert "instance_id:test__repo-42" in body
        assert "METADATA-->" in body

    def test_empty_problem_statement(self):
        body = build_pr_body("")
        assert "(no description)" in body


class TestBuildMetadataBlock:
    def test_simple_block(self):
        block = build_metadata_block({"key1": "value1", "key2": "value2"})
        assert block == "<!--METADATA\nkey1:value1\nkey2:value2\nMETADATA-->"

    def test_multiline_values_escaped(self):
        block = build_metadata_block({"desc": "line1\nline2"})
        assert "line1\\nline2" in block
        assert "\nline2\n" not in block

    def test_none_value(self):
        block = build_metadata_block({"key": None})
        assert "key:" in block


class TestParseMetadataBlock:
    def test_parse_basic(self):
        body = "Some text\n<!--METADATA\nkey1:value1\nkey2:value2\nMETADATA-->\nMore text"
        result = parse_metadata_block(body)
        assert result == {"key1": "value1", "key2": "value2"}

    def test_parse_no_metadata(self):
        result = parse_metadata_block("Just a normal PR body")
        assert result == {}

    def test_parse_escaped_newlines(self):
        body = "<!--METADATA\ndesc:line1\\nline2\nMETADATA-->"
        result = parse_metadata_block(body)
        assert result["desc"] == "line1\nline2"

    def test_parse_value_with_colons(self):
        body = '<!--METADATA\nurl:https://example.com:8080/path\nMETADATA-->'
        result = parse_metadata_block(body)
        assert result["url"] == "https://example.com:8080/path"

    def test_roundtrip(self):
        original = {
            "instance_id": "django__django-16255",
            "version": "4.2",
            "FAIL_TO_PASS": '["test_one", "test_two"]',
            "requirements": "Django>=4.2\npytest>=7.0",
        }
        block = build_metadata_block(original)
        parsed = parse_metadata_block(f"Body text\n\n{block}")
        assert parsed["instance_id"] == original["instance_id"]
        assert parsed["version"] == original["version"]
        assert parsed["FAIL_TO_PASS"] == original["FAIL_TO_PASS"]
        assert parsed["requirements"] == original["requirements"]


class TestUpdateMetadataInBody:
    def test_update_existing(self):
        body = "Body\n<!--METADATA\nold:value\nMETADATA-->"
        new_body = update_metadata_in_body(body, {"new": "value"})
        assert "old:value" not in new_body
        assert "new:value" in new_body

    def test_append_if_missing(self):
        body = "Just a body"
        new_body = update_metadata_in_body(body, {"key": "val"})
        assert "Just a body" in new_body
        assert "<!--METADATA" in new_body
        assert "key:val" in new_body


class TestResolveMetadataFields:
    def test_dynamic_from_field(self):
        config = ["from:instance_id", "from:repo_language"]
        item = {"instance_id": "test-123", "repo_language": "Python"}
        result = resolve_metadata_fields(config, item)
        assert result == {"instance_id": "test-123", "repo_language": "Python"}

    def test_static_dict(self):
        config = [{"dataset": "swe-bench-pro"}]
        result = resolve_metadata_fields(config, {})
        assert result == {"dataset": "swe-bench-pro"}

    def test_static_string_with_colon(self):
        config = ["dataset: swe-bench-pro"]
        result = resolve_metadata_fields(config, {})
        assert result == {"dataset": "swe-bench-pro"}

    def test_missing_field_returns_empty(self):
        config = ["from:nonexistent"]
        result = resolve_metadata_fields(config, {"other": "value"})
        assert result == {"nonexistent": ""}

    def test_mixed_config(self):
        config = [
            "from:instance_id",
            {"dataset": "swe-bench-pro"},
            "from:version",
        ]
        item = {"instance_id": "test-1", "version": "4.2"}
        result = resolve_metadata_fields(config, item)
        assert result["instance_id"] == "test-1"
        assert result["dataset"] == "swe-bench-pro"
        assert result["version"] == "4.2"


class TestRenderPrBodyTemplate:
    def test_basic_rendering(self):
        template = "## Problem\n\n{{ problem_statement }}"
        item = {"problem_statement": "Fix the login bug"}
        result = render_pr_body_template(template, item)
        assert "## Problem" in result
        assert "Fix the login bug" in result

    def test_metadata_keyword_args(self):
        template = '{{ metadata(instance_id=instance_id, repo=repo) }}'
        item = {"instance_id": "django__django-42", "repo": "django/django"}
        result = render_pr_body_template(template, item)
        assert "<!--METADATA" in result
        assert "instance_id:django__django-42" in result
        assert "repo:django/django" in result
        assert "METADATA-->" in result

    def test_metadata_static_string_values(self):
        template = '{{ metadata(dataset="swe-bench-pro", instance_id=instance_id) }}'
        item = {"instance_id": "test-1"}
        result = render_pr_body_template(template, item)
        assert "dataset:swe-bench-pro" in result
        assert "instance_id:test-1" in result

    def test_conditional_sections(self):
        template = (
            "## Problem\n\n{{ problem_statement }}\n\n"
            "{% if hints_text %}## Hints\n\n{{ hints_text }}\n{% endif %}"
        )
        # With hints
        item_with = {"problem_statement": "Bug", "hints_text": "Check X"}
        result_with = render_pr_body_template(template, item_with)
        assert "## Hints" in result_with
        assert "Check X" in result_with

        # Without hints
        item_without = {"problem_statement": "Bug", "hints_text": ""}
        result_without = render_pr_body_template(template, item_without)
        assert "## Hints" not in result_without

    def test_extra_metadata_merging(self):
        template = '{{ metadata(instance_id=instance_id) }}'
        item = {"instance_id": "test-1"}
        result = render_pr_body_template(
            template, item, extra_metadata={"imported_at": "2025-01-01T00:00:00Z"},
        )
        assert "instance_id:test-1" in result
        assert "imported_at:2025-01-01T00:00:00Z" in result

    def test_missing_fields_render_empty(self):
        template = "Value: {{ nonexistent_field }}"
        result = render_pr_body_template(template, {})
        assert "Value: " in result

    def test_default_filter_on_missing(self):
        template = '{{ missing | default("fallback") }}'
        result = render_pr_body_template(template, {})
        assert "fallback" in result

    def test_metadata_roundtrip(self):
        """Rendered metadata block can be parsed back."""
        template = '{{ metadata(instance_id=instance_id, version=version) }}'
        item = {"instance_id": "test-42", "version": "1.0"}
        body = render_pr_body_template(template, item)
        parsed = parse_metadata_block(body)
        assert parsed["instance_id"] == "test-42"
        assert parsed["version"] == "1.0"


class TestRenderPrTitleTemplate:
    def test_first_sentence_period(self):
        template = "{{ problem_statement | first_sentence }}"
        item = {"problem_statement": "Fix the bug. More details here."}
        result = render_pr_title_template(template, item)
        assert result == "Fix the bug."

    def test_first_sentence_newline(self):
        template = "{{ problem_statement | first_sentence }}"
        item = {"problem_statement": "Fix the bug\nMore details here"}
        result = render_pr_title_template(template, item)
        assert result == "Fix the bug"

    def test_first_sentence_no_period_no_newline(self):
        template = "{{ problem_statement | first_sentence }}"
        item = {"problem_statement": "Fix the bug"}
        result = render_pr_title_template(template, item)
        assert result == "Fix the bug"

    def test_truncate_title_long(self):
        template = "{{ text | truncate_title }}"
        long_text = "A" * 300
        result = render_pr_title_template(template, {"text": long_text})
        assert len(result) == 256
        assert result.endswith("...")

    def test_truncate_title_short(self):
        template = "{{ text | truncate_title }}"
        result = render_pr_title_template(template, {"text": "Short title"})
        assert result == "Short title"

    def test_default_title_template(self):
        template = "{{ problem_statement | first_sentence | truncate_title }}"
        item = {"problem_statement": "Fix authentication bypass. Details follow."}
        result = render_pr_title_template(template, item)
        assert result == "Fix authentication bypass."

    def test_all_item_fields_available(self):
        template = "[{{ dataset_label }}] {{ instance_id }}"
        item = {"dataset_label": "swe-bench-pro", "instance_id": "django__django-42"}
        result = render_pr_title_template(template, item)
        assert result == "[swe-bench-pro] django__django-42"

    def test_first_sentence_empty(self):
        template = "{{ problem_statement | first_sentence }}"
        result = render_pr_title_template(template, {"problem_statement": ""})
        assert result == ""
