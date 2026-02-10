"""Capability matching between providers and generators."""

from __future__ import annotations

from ee_bench_generator.metadata import (
    FieldDescriptor,
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

    When a required field name appears with multiple sources (e.g.
    ``description`` from both ``pull_request`` and ``issue``), it is
    treated as a **multi-source requirement**: the provider must
    satisfy at least one source for that field name. Unsatisfied
    source variants are reported in ``missing_optional``, not
    ``missing_required``.

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
    missing_required: list[FieldDescriptor] = []
    missing_optional: list[FieldDescriptor] = []

    # Group required fields by name to detect multi-source requirements.
    # When the same field name appears from multiple sources, the provider
    # only needs to satisfy at least one source (fallback pattern).
    required_by_name: dict[str, list[FieldDescriptor]] = {}
    for field in generator.required_fields:
        required_by_name.setdefault(field.name, []).append(field)

    for name, variants in required_by_name.items():
        if len(variants) == 1:
            # Single source — must be provided
            field = variants[0]
            if not provider.can_provide(field.name, field.source):
                missing_required.append(field)
        else:
            # Multi-source — at least one must be provided
            satisfied = [
                f for f in variants
                if provider.can_provide(f.name, f.source)
            ]
            if not satisfied:
                # None satisfied — report all as missing required
                missing_required.extend(variants)
            else:
                # Some satisfied — unsatisfied variants are informational only
                for f in variants:
                    if not provider.can_provide(f.name, f.source):
                        missing_optional.append(f)

    # Check optional fields
    for field in generator.optional_fields:
        if not provider.can_provide(field.name, field.source):
            missing_optional.append(field)

    return ValidationResult(
        compatible=len(missing_required) == 0,
        missing_required=missing_required,
        missing_optional=missing_optional,
    )


def validate_composite_compatibility(
    providers: list[ProviderMetadata], generator: GeneratorMetadata
) -> ValidationResult:
    """Validate that multiple providers together can satisfy a generator's requirements.

    Merges all providers' fields into a single virtual ProviderMetadata and
    delegates to ``validate_compatibility``.

    Args:
        providers: List of ProviderMetadata from each provider in the composite.
        generator: Generator metadata declaring required fields.

    Returns:
        ValidationResult indicating compatibility and any missing fields.

    Example:
        >>> from ee_bench_generator.metadata import FieldDescriptor, ProviderMetadata, GeneratorMetadata
        >>> p1 = ProviderMetadata(
        ...     name="hf_data",
        ...     sources=["dataset"],
        ...     provided_fields=[FieldDescriptor("repo", "dataset")],
        ... )
        >>> p2 = ProviderMetadata(
        ...     name="github_prs",
        ...     sources=["pull_request"],
        ...     provided_fields=[FieldDescriptor("patch", "pull_request")],
        ... )
        >>> gen = GeneratorMetadata(
        ...     name="importer",
        ...     required_fields=[
        ...         FieldDescriptor("repo", "dataset"),
        ...         FieldDescriptor("patch", "pull_request"),
        ...     ],
        ... )
        >>> result = validate_composite_compatibility([p1, p2], gen)
        >>> result.compatible
        True
    """
    all_fields: list[FieldDescriptor] = []
    all_sources: set[str] = set()
    seen: set[tuple[str, str]] = set()

    for pm in providers:
        for fd in pm.provided_fields:
            key = (fd.name, fd.source)
            if key not in seen:
                all_fields.append(fd)
                seen.add(key)
        all_sources.update(pm.sources)

    merged = ProviderMetadata(
        name="composite",
        sources=sorted(all_sources),
        provided_fields=all_fields,
    )
    return validate_compatibility(merged, generator)
