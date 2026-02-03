"""Tests for DPAIA JVM Generator."""

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from ee_bench_generator.metadata import Context, FieldDescriptor, ProviderMetadata, Selection

from ee_bench_dpaia import DpaiaJvmGenerator


@pytest.fixture
def generator():
    """Create a test generator."""
    return DpaiaJvmGenerator()


@pytest.fixture
def mock_provider():
    """Create a mock provider with all fields available."""
    provider = MagicMock()
    provider.metadata = ProviderMetadata(
        name="mock_provider",
        sources=["pull_request", "repository"],
        provided_fields=[
            FieldDescriptor("description", "pull_request"),
            FieldDescriptor("title", "pull_request"),
            FieldDescriptor("base_commit", "pull_request"),
            FieldDescriptor("patch", "pull_request"),
            FieldDescriptor("FAIL_TO_PASS", "pull_request"),
            FieldDescriptor("PASS_TO_PASS", "pull_request"),
            FieldDescriptor("repo_url", "repository"),
            FieldDescriptor("repo_tree", "repository"),
        ],
    )

    # Set up field return values
    def get_field(name, source, context):
        fields = {
            ("description", "pull_request"): "Fix null pointer exception in Parser",
            ("title", "pull_request"): "Bug fix: NPE in Parser",
            ("base_commit", "pull_request"): "abc123def456abc123def456abc123def456abc1",
            ("patch", "pull_request"): "diff --git a/Parser.java b/Parser.java\n+fix",
            ("FAIL_TO_PASS", "pull_request"): '["test.ParserTest.testNullInput"]',
            ("PASS_TO_PASS", "pull_request"): '["test.ParserTest.testValidInput"]',
            ("repo_url", "repository"): "https://github.com/owner/repo.git",
            ("repo_tree", "repository"): ["src/Parser.java", "test/ParserTest.java"],
        }
        return fields.get((name, source))

    provider.get_field.side_effect = get_field

    # Set up iter_items
    provider.iter_items.return_value = iter([
        {"owner": "owner", "repo": "repo", "number": 42}
    ])

    return provider


@pytest.fixture
def context():
    """Create a test context."""
    return Context(
        selection=Selection(
            resource="pull_requests",
            filters={"repo": "owner/repo", "pr_numbers": [42]},
        )
    )


class TestDpaiaJvmGeneratorMetadata:
    """Tests for generator metadata."""

    def test_metadata_name(self, generator):
        """Test generator name."""
        assert generator.metadata.name == "dpaia_jvm"

    def test_required_fields(self, generator):
        """Test required fields are declared."""
        required_names = {f.name for f in generator.metadata.required_fields}

        assert "description" in required_names
        assert "base_commit" in required_names
        assert "patch" in required_names
        assert "repo_url" in required_names

    def test_optional_fields(self, generator):
        """Test optional fields are declared."""
        optional_names = {f.name for f in generator.metadata.optional_fields}

        assert "title" in optional_names
        assert "FAIL_TO_PASS" in optional_names
        assert "PASS_TO_PASS" in optional_names
        assert "hints_text" in optional_names


class TestDpaiaJvmGeneratorOutputSchema:
    """Tests for output schema."""

    def test_schema_has_required_fields(self, generator):
        """Test schema declares required fields."""
        schema = generator.output_schema()

        assert "instance_id" in schema["required"]
        assert "repo" in schema["required"]
        assert "base_commit" in schema["required"]
        assert "patch" in schema["required"]
        assert "problem_statement" in schema["required"]
        assert "FAIL_TO_PASS" in schema["required"]
        assert "PASS_TO_PASS" in schema["required"]
        assert "created_at" in schema["required"]

    def test_schema_has_property_definitions(self, generator):
        """Test schema has property definitions."""
        schema = generator.output_schema()

        assert "instance_id" in schema["properties"]
        assert "repo" in schema["properties"]
        assert "base_commit" in schema["properties"]
        assert "hints_text" in schema["properties"]

    def test_schema_is_valid_json_schema(self, generator):
        """Test schema is valid JSON Schema."""
        schema = generator.output_schema()

        assert schema.get("$schema") is not None
        assert schema.get("type") == "object"
        assert "properties" in schema


class TestDpaiaJvmGeneratorGenerate:
    """Tests for generate method."""

    def test_generates_record(self, generator, mock_provider, context):
        """Test generating a single record."""
        records = list(generator.generate(mock_provider, context))

        assert len(records) == 1
        record = records[0]

        assert record["instance_id"] == "owner__repo__42"
        assert record["repo"] == "https://github.com/owner/repo.git"
        assert record["base_commit"] == "abc123def456abc123def456abc123def456abc1"
        assert "diff --git" in record["patch"]

    def test_problem_statement_includes_title_and_description(
        self, generator, mock_provider, context
    ):
        """Test problem statement combines title and description."""
        records = list(generator.generate(mock_provider, context))
        record = records[0]

        assert "Bug fix: NPE in Parser" in record["problem_statement"]
        assert "Fix null pointer exception in Parser" in record["problem_statement"]

    def test_includes_test_fields(self, generator, mock_provider, context):
        """Test FAIL_TO_PASS and PASS_TO_PASS are included."""
        records = list(generator.generate(mock_provider, context))
        record = records[0]

        fail_to_pass = json.loads(record["FAIL_TO_PASS"])
        pass_to_pass = json.loads(record["PASS_TO_PASS"])

        assert fail_to_pass == ["test.ParserTest.testNullInput"]
        assert pass_to_pass == ["test.ParserTest.testValidInput"]

    def test_includes_created_at_timestamp(self, generator, mock_provider, context):
        """Test created_at is a valid ISO8601 timestamp."""
        records = list(generator.generate(mock_provider, context))
        record = records[0]

        # Should be parseable as datetime with UTC timezone
        created_at = record["created_at"]
        # Accept both Z and +00:00 suffixes for UTC
        assert created_at.endswith("Z") or created_at.endswith("+00:00")
        # Normalize and parse
        normalized = created_at.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        assert parsed.tzinfo is not None

    def test_multiple_items(self, generator, mock_provider, context):
        """Test generating multiple records."""
        mock_provider.iter_items.return_value = iter([
            {"owner": "owner", "repo": "repo", "number": 1},
            {"owner": "owner", "repo": "repo", "number": 2},
            {"owner": "owner", "repo": "repo", "number": 3},
        ])

        records = list(generator.generate(mock_provider, context))

        assert len(records) == 3
        assert records[0]["instance_id"] == "owner__repo__1"
        assert records[1]["instance_id"] == "owner__repo__2"
        assert records[2]["instance_id"] == "owner__repo__3"

    def test_handles_missing_optional_fields(self, generator, context):
        """Test graceful handling of missing optional fields."""
        provider = MagicMock()
        provider.metadata = ProviderMetadata(
            name="minimal_provider",
            sources=["pull_request", "repository"],
            provided_fields=[
                FieldDescriptor("description", "pull_request"),
                FieldDescriptor("base_commit", "pull_request"),
                FieldDescriptor("patch", "pull_request"),
                FieldDescriptor("repo_url", "repository"),
            ],
        )

        def get_field(name, source, ctx):
            fields = {
                ("description", "pull_request"): "Description only",
                ("base_commit", "pull_request"): "abc123def456abc123def456abc123def456abc1",
                ("patch", "pull_request"): "diff content",
                ("repo_url", "repository"): "https://github.com/owner/repo.git",
            }
            return fields.get((name, source))

        provider.get_field.side_effect = get_field
        provider.iter_items.return_value = iter([
            {"owner": "owner", "repo": "repo", "number": 1}
        ])

        records = list(generator.generate(provider, context))
        record = records[0]

        # Optional fields should have defaults
        assert record["FAIL_TO_PASS"] == "[]"
        assert record["PASS_TO_PASS"] == "[]"
        assert record["hints_text"] == ""
        # Problem statement should just be description without title
        assert record["problem_statement"] == "Description only"

    def test_empty_provider_yields_no_records(self, generator, mock_provider, context):
        """Test empty provider yields no records."""
        mock_provider.iter_items.return_value = iter([])

        records = list(generator.generate(mock_provider, context))

        assert records == []


class TestBuildProblemStatement:
    """Tests for problem statement building."""

    def test_title_and_description(self, generator):
        """Test combining title and description."""
        result = generator._build_problem_statement(
            "Title Here", "Description here"
        )
        assert result == "Title Here\n\nDescription here"

    def test_title_only(self, generator):
        """Test with title only."""
        result = generator._build_problem_statement("Title Here", "")
        assert result == "Title Here"

    def test_description_only(self, generator):
        """Test with description only."""
        result = generator._build_problem_statement("", "Description here")
        assert result == "Description here"

    def test_both_empty(self, generator):
        """Test with both empty."""
        result = generator._build_problem_statement("", "")
        assert result == ""
