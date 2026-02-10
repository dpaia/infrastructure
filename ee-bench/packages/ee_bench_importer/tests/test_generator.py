"""Tests for GitHubPRImporterGenerator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ee_bench_generator.metadata import Context, FieldDescriptor, ProviderMetadata, Selection

from ee_bench_importer.generator import GitHubPRImporterGenerator


@pytest.fixture
def generator():
    return GitHubPRImporterGenerator()


class TestMetadata:
    def test_generator_name(self, generator):
        assert generator.metadata.name == "github_pr_importer"

    def test_required_fields(self, generator):
        required = generator.metadata.required_fields
        names = {f.name for f in required}
        assert "instance_id" in names
        assert "repo" in names
        assert "base_commit" in names
        assert "patch" in names
        assert "problem_statement" in names
        assert "checksum" in names

    def test_optional_fields(self, generator):
        optional = generator.metadata.optional_fields
        names = {f.name for f in optional}
        assert "test_patch" in names
        assert "hints_text" in names
        assert "repo_language" in names


class TestOutputSchema:
    def test_schema_has_required_fields(self, generator):
        schema = generator.output_schema()
        assert "instance_id" in schema["required"]
        assert "status" in schema["required"]

    def test_schema_properties(self, generator):
        schema = generator.output_schema()
        props = schema["properties"]
        assert "pr_url" in props
        assert "pr_number" in props
        assert "error" in props


class TestResolveListValues:
    def test_static_values(self, generator):
        result = generator._resolve_list_values(
            ["label1", "label2"], {}
        )
        assert result == ["label1", "label2"]

    def test_dynamic_from_field(self, generator):
        result = generator._resolve_list_values(
            ["from:repo_language"],
            {"repo_language": "Python"},
        )
        assert "python" in result

    def test_mixed_values(self, generator):
        result = generator._resolve_list_values(
            ["swe-bench-pro", "from:repo_language"],
            {"repo_language": "Java"},
        )
        assert "swe-bench-pro" in result
        assert "java" in result

    def test_empty_dynamic_field_skipped(self, generator):
        result = generator._resolve_list_values(
            ["from:missing_field"],
            {},
        )
        assert result == []

    def test_cpp_normalization(self, generator):
        result = generator._resolve_list_values(
            ["from:repo_language"],
            {"repo_language": "C++"},
        )
        assert "cplus" in result[0] or "c++" in [r.lower() for r in result]

    def test_jinja2_simple_field(self, generator):
        result = generator._resolve_list_values(
            ["{{ repo_language }}"],
            {"repo_language": "Python"},
        )
        assert "python" in result

    def test_jinja2_mixed_with_static(self, generator):
        result = generator._resolve_list_values(
            ["swe-bench-pro", "{{ repo_language }}"],
            {"repo_language": "Java"},
        )
        assert "swe-bench-pro" in result
        assert "java" in result

    def test_jinja2_empty_field_skipped(self, generator):
        result = generator._resolve_list_values(
            ["{{ missing_field }}"],
            {},
        )
        assert result == []

    def test_jinja2_json_array_expansion(self, generator):
        result = generator._resolve_list_values(
            ["{{ issue_categories }}"],
            {"issue_categories": '["bug", "feature"]'},
        )
        assert "bug" in result
        assert "feature" in result

    def test_jinja2_cpp_normalization(self, generator):
        result = generator._resolve_list_values(
            ["{{ repo_language }}"],
            {"repo_language": "C++"},
        )
        assert "cplusplus" in result


class TestGenerateDryRun:
    def test_dry_run_skips_github(self, generator):
        """Dry run should not require GitHub token."""
        # Create mock provider
        provider = MagicMock()
        provider.metadata = ProviderMetadata(
            name="huggingface_dataset",
            sources=["dataset_item", "dataset_metadata"],
            provided_fields=[
                FieldDescriptor("instance_id", source="dataset_item"),
                FieldDescriptor("repo", source="dataset_item"),
                FieldDescriptor("base_commit", source="dataset_item"),
                FieldDescriptor("patch", source="dataset_item"),
                FieldDescriptor("problem_statement", source="dataset_item"),
                FieldDescriptor("checksum", source="dataset_metadata"),
            ],
        )

        items = [
            {
                "instance_id": "test__repo-1",
                "repo": "test/repo",
                "base_commit": "abc123",
                "patch": "diff ...",
                "problem_statement": "Fix bug",
            }
        ]
        provider.iter_items.return_value = iter(items)

        def mock_get_field(name, source, ctx):
            if source == "dataset_metadata" and name == "checksum":
                return "checksum123"
            return ctx.current_item.get(name, "")

        provider.get_field = mock_get_field

        context = Context(
            selection=Selection(resource="dataset_items", filters={}),
            options={
                "generator_options": {
                    "dry_run": True,
                    "state_file": "/tmp/test-state.json",
                }
            },
        )

        results = list(generator.generate(provider, context))
        assert len(results) == 1
        assert results[0]["status"] == "dry_run_create"
        assert results[0]["instance_id"] == "test__repo-1"
