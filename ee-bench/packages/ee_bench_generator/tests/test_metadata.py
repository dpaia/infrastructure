"""Tests for metadata types."""

import pytest

from ee_bench_generator.metadata import (
    Context,
    FieldDescriptor,
    GeneratorMetadata,
    ProviderMetadata,
    Selection,
    ValidationResult,
)


class TestFieldDescriptor:
    """Tests for FieldDescriptor dataclass."""

    def test_create_with_defaults(self):
        """Test creating FieldDescriptor with default values."""
        field = FieldDescriptor(name="description", source="pull_request")

        assert field.name == "description"
        assert field.source == "pull_request"
        assert field.required is True
        assert field.description == ""

    def test_create_with_all_values(self):
        """Test creating FieldDescriptor with all values specified."""
        field = FieldDescriptor(
            name="patch",
            source="pull_request",
            required=False,
            description="The unified diff patch",
        )

        assert field.name == "patch"
        assert field.source == "pull_request"
        assert field.required is False
        assert field.description == "The unified diff patch"

    def test_create_without_source(self):
        """Test creating FieldDescriptor without source defaults to empty string."""
        field = FieldDescriptor("patch")

        assert field.name == "patch"
        assert field.source == ""
        assert field.required is True


class TestProviderMetadata:
    """Tests for ProviderMetadata dataclass."""

    def test_create_provider_metadata(self):
        """Test creating ProviderMetadata."""
        fields = [
            FieldDescriptor("description", "pull_request"),
            FieldDescriptor("patch", "pull_request"),
            FieldDescriptor("repo_tree", "repository"),
        ]
        metadata = ProviderMetadata(
            name="github_pull_requests",
            sources=["pull_request", "repository"],
            provided_fields=fields,
        )

        assert metadata.name == "github_pull_requests"
        assert metadata.sources == ["pull_request", "repository"]
        assert len(metadata.provided_fields) == 3

    def test_can_provide_returns_true_for_existing_field(self):
        """Test can_provide returns True when field exists."""
        fields = [
            FieldDescriptor("description", "pull_request"),
            FieldDescriptor("repo_tree", "repository"),
        ]
        metadata = ProviderMetadata(
            name="test", sources=["pull_request", "repository"], provided_fields=fields
        )

        assert metadata.can_provide("description", "pull_request") is True
        assert metadata.can_provide("repo_tree", "repository") is True

    def test_can_provide_returns_false_for_missing_field(self):
        """Test can_provide returns False when field doesn't exist."""
        fields = [FieldDescriptor("description", "pull_request")]
        metadata = ProviderMetadata(
            name="test", sources=["pull_request"], provided_fields=fields
        )

        assert metadata.can_provide("patch", "pull_request") is False

    def test_can_provide_returns_false_for_wrong_source(self):
        """Test can_provide returns False when source doesn't match."""
        fields = [FieldDescriptor("description", "pull_request")]
        metadata = ProviderMetadata(
            name="test", sources=["pull_request"], provided_fields=fields
        )

        # Field exists but with different source
        assert metadata.can_provide("description", "issue") is False

    def test_can_provide_name_only_match(self):
        """Test can_provide with empty source matches by name only."""
        fields = [FieldDescriptor("description", "pull_request")]
        metadata = ProviderMetadata(
            name="test", sources=["pull_request"], provided_fields=fields
        )

        assert metadata.can_provide("description", "") is True

    def test_can_provide_name_only_no_match(self):
        """Test can_provide with empty source returns False when name missing."""
        fields = [FieldDescriptor("description", "pull_request")]
        metadata = ProviderMetadata(
            name="test", sources=["pull_request"], provided_fields=fields
        )

        assert metadata.can_provide("missing", "") is False

    def test_find_source_for_field(self):
        """Test find_source_for_field returns the source of the matching field."""
        fields = [
            FieldDescriptor("description", "pull_request"),
            FieldDescriptor("repo_tree", "repository"),
        ]
        metadata = ProviderMetadata(
            name="test", sources=["pull_request", "repository"], provided_fields=fields
        )

        assert metadata.find_source_for_field("description") == "pull_request"
        assert metadata.find_source_for_field("repo_tree") == "repository"

    def test_find_source_for_field_not_found(self):
        """Test find_source_for_field returns empty string when not found."""
        fields = [FieldDescriptor("description", "pull_request")]
        metadata = ProviderMetadata(
            name="test", sources=["pull_request"], provided_fields=fields
        )

        assert metadata.find_source_for_field("missing") == ""


class TestGeneratorMetadata:
    """Tests for GeneratorMetadata dataclass."""

    def test_create_with_required_fields_only(self):
        """Test creating GeneratorMetadata with only required fields."""
        required = [
            FieldDescriptor("description", "pull_request"),
            FieldDescriptor("patch", "pull_request"),
        ]
        metadata = GeneratorMetadata(name="dpaia_jvm", required_fields=required)

        assert metadata.name == "dpaia_jvm"
        assert len(metadata.required_fields) == 2
        assert metadata.optional_fields == []

    def test_create_with_optional_fields(self):
        """Test creating GeneratorMetadata with optional fields."""
        required = [FieldDescriptor("description", "pull_request")]
        optional = [
            FieldDescriptor("title", "pull_request", required=False),
            FieldDescriptor("labels", "pull_request", required=False),
        ]
        metadata = GeneratorMetadata(
            name="dpaia_jvm", required_fields=required, optional_fields=optional
        )

        assert len(metadata.required_fields) == 1
        assert len(metadata.optional_fields) == 2


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_compatible_result(self):
        """Test creating a compatible ValidationResult."""
        result = ValidationResult(
            compatible=True, missing_required=[], missing_optional=[]
        )

        assert result.compatible is True
        assert result.missing_required == []
        assert result.missing_optional == []

    def test_incompatible_result_with_missing_required(self):
        """Test creating an incompatible ValidationResult."""
        missing = [FieldDescriptor("patch", "pull_request")]
        result = ValidationResult(
            compatible=False, missing_required=missing, missing_optional=[]
        )

        assert result.compatible is False
        assert len(result.missing_required) == 1
        assert result.missing_required[0].name == "patch"


class TestSelection:
    """Tests for Selection dataclass."""

    def test_create_with_defaults(self):
        """Test creating Selection with default limit."""
        selection = Selection(
            resource="pull_requests", filters={"repo": "org/repo", "pr_numbers": [42]}
        )

        assert selection.resource == "pull_requests"
        assert selection.filters == {"repo": "org/repo", "pr_numbers": [42]}
        assert selection.limit is None

    def test_create_with_limit(self):
        """Test creating Selection with explicit limit."""
        selection = Selection(
            resource="issues", filters={"labels": ["bug"]}, limit=100
        )

        assert selection.resource == "issues"
        assert selection.limit == 100


class TestContext:
    """Tests for Context dataclass."""

    def test_create_with_defaults(self):
        """Test creating Context with default values."""
        selection = Selection(resource="pull_requests", filters={})
        context = Context(selection=selection)

        assert context.selection is selection
        assert context.options == {}
        assert context.current_item is None

    def test_create_with_all_values(self):
        """Test creating Context with all values specified."""
        selection = Selection(resource="pull_requests", filters={})
        options = {"provider_options": {"token": "abc"}}
        current_item = {"repo": "org/repo", "number": 42}

        context = Context(
            selection=selection, options=options, current_item=current_item
        )

        assert context.selection is selection
        assert context.options == options
        assert context.current_item == current_item
