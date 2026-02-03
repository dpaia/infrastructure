"""Tests for test field parser."""

import json

import pytest

from ee_bench_github.test_field_parser import ParsedTestFields, parse_test_fields


class TestParseTestFields:
    """Tests for parse_test_fields function."""

    def test_empty_text_returns_empty_arrays(self):
        """Test that empty text returns empty arrays."""
        result = parse_test_fields("")

        assert result.fail_to_pass == "[]"
        assert result.pass_to_pass == "[]"

    def test_none_text_returns_empty_arrays(self):
        """Test that None-like text returns empty arrays."""
        result = parse_test_fields("")

        assert result.fail_to_pass == "[]"
        assert result.pass_to_pass == "[]"

    def test_no_markers_returns_empty_arrays(self):
        """Test that text without markers returns empty arrays."""
        result = parse_test_fields("This is a PR description without any test markers.")

        assert result.fail_to_pass == "[]"
        assert result.pass_to_pass == "[]"

    def test_inline_json_array(self):
        """Test parsing inline JSON array format."""
        text = 'FAIL_TO_PASS: ["test1", "test2"]\nPASS_TO_PASS: ["test3"]'

        result = parse_test_fields(text)

        assert json.loads(result.fail_to_pass) == ["test1", "test2"]
        assert json.loads(result.pass_to_pass) == ["test3"]

    def test_comma_separated_list(self):
        """Test parsing comma-separated list format."""
        text = "FAIL_TO_PASS: test1, test2, test3\nPASS_TO_PASS: test4"

        result = parse_test_fields(text)

        assert json.loads(result.fail_to_pass) == ["test1", "test2", "test3"]
        assert json.loads(result.pass_to_pass) == ["test4"]

    def test_header_style_format(self):
        """Test parsing header style format."""
        text = """## Description
Some description here.

## FAIL_TO_PASS
["test1", "test2"]

## PASS_TO_PASS
["test3"]
"""
        result = parse_test_fields(text)

        assert json.loads(result.fail_to_pass) == ["test1", "test2"]
        assert json.loads(result.pass_to_pass) == ["test3"]

    def test_case_insensitive_markers(self):
        """Test that markers are case-insensitive."""
        text = 'fail_to_pass: ["test1"]\nPass_To_Pass: ["test2"]'

        result = parse_test_fields(text)

        assert json.loads(result.fail_to_pass) == ["test1"]
        assert json.loads(result.pass_to_pass) == ["test2"]

    def test_single_test_without_array(self):
        """Test parsing single test without array brackets."""
        text = "FAIL_TO_PASS: single_test"

        result = parse_test_fields(text)

        assert json.loads(result.fail_to_pass) == ["single_test"]

    def test_mixed_formats(self):
        """Test parsing mixed formats in same text."""
        text = """## FAIL_TO_PASS
test1, test2

PASS_TO_PASS: ["test3", "test4"]
"""
        result = parse_test_fields(text)

        assert json.loads(result.fail_to_pass) == ["test1", "test2"]
        assert json.loads(result.pass_to_pass) == ["test3", "test4"]

    def test_whitespace_handling(self):
        """Test that whitespace is handled correctly."""
        text = "FAIL_TO_PASS:   test1 ,  test2  ,test3  "

        result = parse_test_fields(text)

        assert json.loads(result.fail_to_pass) == ["test1", "test2", "test3"]

    def test_quoted_items_in_list(self):
        """Test parsing quoted items in comma-separated list."""
        text = 'FAIL_TO_PASS: "test1", "test2"'

        result = parse_test_fields(text)

        assert json.loads(result.fail_to_pass) == ["test1", "test2"]

    def test_empty_value_after_marker(self):
        """Test empty value after marker."""
        text = "FAIL_TO_PASS: \nPASS_TO_PASS: test1"

        result = parse_test_fields(text)

        # Empty FAIL_TO_PASS should return []
        assert result.fail_to_pass == "[]"
        assert json.loads(result.pass_to_pass) == ["test1"]

    def test_only_fail_to_pass(self):
        """Test when only FAIL_TO_PASS is present."""
        text = 'FAIL_TO_PASS: ["only_fail_test"]'

        result = parse_test_fields(text)

        assert json.loads(result.fail_to_pass) == ["only_fail_test"]
        assert result.pass_to_pass == "[]"

    def test_only_pass_to_pass(self):
        """Test when only PASS_TO_PASS is present."""
        text = 'PASS_TO_PASS: ["only_pass_test"]'

        result = parse_test_fields(text)

        assert result.fail_to_pass == "[]"
        assert json.loads(result.pass_to_pass) == ["only_pass_test"]

    def test_real_world_pr_body(self):
        """Test with realistic PR body format."""
        text = """## Summary
This PR fixes a bug in the authentication module.

## Changes
- Fixed token validation
- Updated tests

## FAIL_TO_PASS
["test_auth_invalid_token", "test_auth_expired_token"]

## PASS_TO_PASS
["test_auth_valid_token", "test_auth_refresh"]

## Notes
Please review carefully.
"""
        result = parse_test_fields(text)

        assert json.loads(result.fail_to_pass) == [
            "test_auth_invalid_token",
            "test_auth_expired_token",
        ]
        assert json.loads(result.pass_to_pass) == [
            "test_auth_valid_token",
            "test_auth_refresh",
        ]

    def test_code_block_markers_stripped(self):
        """Test that markdown code block markers are stripped."""
        text = """## FAIL_TO_PASS
```json
["test1", "test2"]
```
"""
        result = parse_test_fields(text)

        assert json.loads(result.fail_to_pass) == ["test1", "test2"]


class TestParsedTestFieldsDataclass:
    """Tests for ParsedTestFields dataclass."""

    def test_creation(self):
        """Test creating ParsedTestFields."""
        fields = ParsedTestFields(fail_to_pass='["test1"]', pass_to_pass='["test2"]')

        assert fields.fail_to_pass == '["test1"]'
        assert fields.pass_to_pass == '["test2"]'
