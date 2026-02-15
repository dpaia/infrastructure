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

    def test_multi_source_compatible_when_one_source_satisfied(self):
        """When same field name is required from multiple sources, at least one must match."""
        provider = ProviderMetadata(
            name="github_issues",
            sources=["issue"],
            provided_fields=[
                FieldDescriptor("description", "issue"),
                FieldDescriptor("patch", "issue"),
                FieldDescriptor("base_commit", "issue"),
            ],
        )
        generator = GeneratorMetadata(
            name="dpaia_jvm",
            required_fields=[
                # Same field from two sources — fallback pattern
                FieldDescriptor("description", "pull_request"),
                FieldDescriptor("description", "issue"),
                FieldDescriptor("patch", "pull_request"),
                FieldDescriptor("patch", "issue"),
                FieldDescriptor("base_commit", "pull_request"),
                FieldDescriptor("base_commit", "issue"),
            ],
        )

        result = validate_compatibility(provider, generator)

        assert result.compatible is True
        assert result.missing_required == []
        # The unsatisfied pull_request variants are reported as optional
        missing_optional_names = {(f.name, f.source) for f in result.missing_optional}
        assert ("description", "pull_request") in missing_optional_names
        assert ("patch", "pull_request") in missing_optional_names
        assert ("base_commit", "pull_request") in missing_optional_names

    def test_multi_source_incompatible_when_no_source_satisfied(self):
        """When same field name from multiple sources, none satisfied -> missing required."""
        provider = ProviderMetadata(
            name="empty_provider",
            sources=["repository"],
            provided_fields=[
                FieldDescriptor("repo_url", "repository"),
            ],
        )
        generator = GeneratorMetadata(
            name="test_generator",
            required_fields=[
                FieldDescriptor("description", "pull_request"),
                FieldDescriptor("description", "issue"),
            ],
        )

        result = validate_compatibility(provider, generator)

        assert result.compatible is False
        assert len(result.missing_required) == 2

    def test_multi_source_all_satisfied(self):
        """When all source variants are satisfied, no missing at all."""
        provider = ProviderMetadata(
            name="full_provider",
            sources=["pull_request", "issue"],
            provided_fields=[
                FieldDescriptor("description", "pull_request"),
                FieldDescriptor("description", "issue"),
            ],
        )
        generator = GeneratorMetadata(
            name="test_generator",
            required_fields=[
                FieldDescriptor("description", "pull_request"),
                FieldDescriptor("description", "issue"),
            ],
        )

        result = validate_compatibility(provider, generator)

        assert result.compatible is True
        assert result.missing_required == []
        assert result.missing_optional == []

    def test_source_less_required_field_satisfied(self):
        """Source-less FieldDescriptor matches any provider with that field name."""
        provider = ProviderMetadata(
            name="test_provider",
            sources=["pull_request"],
            provided_fields=[
                FieldDescriptor("patch", "pull_request"),
            ],
        )
        generator = GeneratorMetadata(
            name="test_generator",
            required_fields=[
                FieldDescriptor("patch"),  # no source
            ],
        )

        result = validate_compatibility(provider, generator)

        assert result.compatible is True
        assert result.missing_required == []

    def test_source_less_required_field_not_satisfied(self):
        """Source-less FieldDescriptor fails when no provider has that field name."""
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
                FieldDescriptor("patch"),  # no source, not provided
            ],
        )

        result = validate_compatibility(provider, generator)

        assert result.compatible is False
        assert len(result.missing_required) == 1
        assert result.missing_required[0].name == "patch"

    def test_source_less_optional_field_reports_missing(self):
        """Source-less optional field is reported as missing when not available."""
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
            optional_fields=[
                FieldDescriptor("labels", required=False),  # no source
            ],
        )

        result = validate_compatibility(provider, generator)

        assert result.compatible is True
        assert len(result.missing_optional) == 1
        assert result.missing_optional[0].name == "labels"

    def test_explicit_source_still_requires_exact_match(self):
        """Backward-compatible: explicit source requires exact match."""
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
