"""Capability matching between providers and generators."""

from __future__ import annotations

from ee_bench_generator.metadata import (
    GeneratorMetadata,
    ProviderMetadata,
    ValidationResult,
)


def validate_compatibility(
    provider: ProviderMetadata, generator: GeneratorMetadata
) -> ValidationResult:
    """Validate that a provider can satisfy a generator's requirements.

    Checks whether the provider can supply all required fields and
    notes which optional fields are missing.

    Args:
        provider: Provider metadata declaring available fields.
        generator: Generator metadata declaring required fields.

    Returns:
        ValidationResult indicating compatibility and any missing fields.

    Example:
        >>> from ee_bench_generator.metadata import FieldDescriptor, ProviderMetadata, GeneratorMetadata
        >>> provider = ProviderMetadata(
        ...     name="test_provider",
        ...     sources=["pull_request"],
        ...     provided_fields=[
        ...         FieldDescriptor("description", "pull_request"),
        ...         FieldDescriptor("patch", "pull_request"),
        ...     ]
        ... )
        >>> generator = GeneratorMetadata(
        ...     name="test_generator",
        ...     required_fields=[
        ...         FieldDescriptor("description", "pull_request"),
        ...     ],
        ...     optional_fields=[
        ...         FieldDescriptor("title", "pull_request", required=False),
        ...     ]
        ... )
        >>> result = validate_compatibility(provider, generator)
        >>> result.compatible
        True
        >>> len(result.missing_required)
        0
        >>> len(result.missing_optional)
        1
    """
    missing_required = []
    missing_optional = []

    # Check required fields
    for field in generator.required_fields:
        if not provider.can_provide(field.name, field.source):
            missing_required.append(field)

    # Check optional fields
    for field in generator.optional_fields:
        if not provider.can_provide(field.name, field.source):
            missing_optional.append(field)

    return ValidationResult(
        compatible=len(missing_required) == 0,
        missing_required=missing_required,
        missing_optional=missing_optional,
    )
