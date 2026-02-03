"""Tests for capability matching."""

import pytest

from ee_bench_generator.matcher import validate_compatibility
from ee_bench_generator.metadata import FieldDescriptor, GeneratorMetadata, ProviderMetadata


class TestValidateCompatibility:
    """Tests for validate_compatibility function."""

    def test_compatible_when_all_required_fields_provided(self):
        """Test compatibility when provider has all required fields."""
        provider = ProviderMetadata(
            name="test_provider",
            sources=["pull_request", "repository"],
            provided_fields=[
                FieldDescriptor("description", "pull_request"),
                FieldDescriptor("patch", "pull_request"),
                FieldDescriptor("repo_tree", "repository"),
            ],
        )
        generator = GeneratorMetadata(
            name="test_generator",
            required_fields=[
                FieldDescriptor("description", "pull_request"),
                FieldDescriptor("patch", "pull_request"),
            ],
        )

        result = validate_compatibility(provider, generator)

        assert result.compatible is True
        assert result.missing_required == []

    def test_incompatible_when_required_field_missing(self):
        """Test incompatibility when provider lacks a required field."""
        provider = ProviderMetadata(
            name="test_provider",
            sources=["pull_request"],
            provided_fields=[
                FieldDescriptor("description", "pull_request"),
            ],
        )
        generator = GeneratorMetadata(
            name="test_generator",
            required_fields=[
                FieldDescriptor("description", "pull_request"),
                FieldDescriptor("patch", "pull_request"),
            ],
        )

        result = validate_compatibility(provider, generator)

        assert result.compatible is False
        assert len(result.missing_required) == 1
        assert result.missing_required[0].name == "patch"

    def test_compatible_with_missing_optional_fields(self):
        """Test that missing optional fields don't affect compatibility."""
        provider = ProviderMetadata(
            name="test_provider",
            sources=["pull_request"],
            provided_fields=[
                FieldDescriptor("description", "pull_request"),
            ],
        )
        generator = GeneratorMetadata(
            name="test_generator",
            required_fields=[
                FieldDescriptor("description", "pull_request"),
            ],
            optional_fields=[
                FieldDescriptor("title", "pull_request", required=False),
                FieldDescriptor("labels", "pull_request", required=False),
            ],
        )

        result = validate_compatibility(provider, generator)

        assert result.compatible is True
        assert result.missing_required == []
        assert len(result.missing_optional) == 2

    def test_reports_missing_optional_fields(self):
        """Test that missing optional fields are reported."""
        provider = ProviderMetadata(
            name="test_provider",
            sources=["pull_request"],
            provided_fields=[
                FieldDescriptor("description", "pull_request"),
                FieldDescriptor("title", "pull_request"),
            ],
        )
        generator = GeneratorMetadata(
            name="test_generator",
            required_fields=[
                FieldDescriptor("description", "pull_request"),
            ],
            optional_fields=[
                FieldDescriptor("title", "pull_request", required=False),
                FieldDescriptor("labels", "pull_request", required=False),
            ],
        )

        result = validate_compatibility(provider, generator)

        assert result.compatible is True
        assert len(result.missing_optional) == 1
        assert result.missing_optional[0].name == "labels"

    def test_incompatible_when_source_mismatch(self):
        """Test incompatibility when field exists but from wrong source."""
        provider = ProviderMetadata(
            name="test_provider",
            sources=["issue"],
            provided_fields=[
                FieldDescriptor("description", "issue"),
            ],
        )
        generator = GeneratorMetadata(
            name="test_generator",
            required_fields=[
                FieldDescriptor("description", "pull_request"),
            ],
        )

        result = validate_compatibility(provider, generator)

        assert result.compatible is False
        assert len(result.missing_required) == 1

    def test_empty_generator_requirements(self):
        """Test compatibility when generator has no requirements."""
        provider = ProviderMetadata(
            name="test_provider",
            sources=["pull_request"],
            provided_fields=[
                FieldDescriptor("description", "pull_request"),
            ],
        )
        generator = GeneratorMetadata(
            name="test_generator",
            required_fields=[],
            optional_fields=[],
        )

        result = validate_compatibility(provider, generator)

        assert result.compatible is True
        assert result.missing_required == []
        assert result.missing_optional == []

    def test_multiple_missing_required_fields(self):
        """Test reporting multiple missing required fields."""
        provider = ProviderMetadata(
            name="test_provider",
            sources=["pull_request"],
            provided_fields=[],
        )
        generator = GeneratorMetadata(
            name="test_generator",
            required_fields=[
                FieldDescriptor("description", "pull_request"),
                FieldDescriptor("patch", "pull_request"),
                FieldDescriptor("base_commit", "pull_request"),
            ],
        )

        result = validate_compatibility(provider, generator)

        assert result.compatible is False
        assert len(result.missing_required) == 3
        missing_names = {f.name for f in result.missing_required}
        assert missing_names == {"description", "patch", "base_commit"}
