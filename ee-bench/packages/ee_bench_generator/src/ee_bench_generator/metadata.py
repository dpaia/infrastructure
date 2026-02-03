"""Metadata types for provider and generator plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldDescriptor:
    """Describes a data field that can be provided or required.

    Attributes:
        name: The field name (e.g., "description", "patch", "FAIL_TO_PASS").
        source: The data source (e.g., "pull_request", "issue", "repository").
        required: Whether the field is mandatory (default: True).
        description: Human-readable description of the field.
    """

    name: str
    source: str
    required: bool = True
    description: str = ""


@dataclass
class ProviderMetadata:
    """Metadata declaring what a provider can supply.

    Attributes:
        name: Provider name (e.g., "github_pull_requests").
        sources: List of data sources this provider supports.
        provided_fields: List of fields this provider can supply.
    """

    name: str
    sources: list[str]
    provided_fields: list[FieldDescriptor]

    def can_provide(self, name: str, source: str) -> bool:
        """Check if this provider can supply a specific field from a source.

        Args:
            name: The field name to check.
            source: The source to check.

        Returns:
            True if the provider can supply this field from this source.
        """
        return any(
            f.name == name and f.source == source for f in self.provided_fields
        )


@dataclass
class GeneratorMetadata:
    """Metadata declaring what a generator requires.

    Attributes:
        name: Generator name (e.g., "dpaia_jvm").
        required_fields: Fields that must be provided.
        optional_fields: Fields that may be provided if available.
    """

    name: str
    required_fields: list[FieldDescriptor]
    optional_fields: list[FieldDescriptor] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of validating provider/generator compatibility.

    Attributes:
        compatible: True if provider can satisfy all required fields.
        missing_required: Required fields the provider cannot supply.
        missing_optional: Optional fields the provider cannot supply.
    """

    compatible: bool
    missing_required: list[FieldDescriptor]
    missing_optional: list[FieldDescriptor]


@dataclass
class Selection:
    """Specifies which items to process.

    Attributes:
        resource: The resource type (e.g., "pull_requests", "issues").
        filters: Filter criteria (e.g., {"repo": "org/repo", "pr_numbers": [42]}).
        limit: Maximum number of items to process (None for no limit).
    """

    resource: str
    filters: dict[str, Any]
    limit: int | None = None


@dataclass
class Context:
    """Runtime context passed during generation.

    Attributes:
        selection: The selection criteria for this run.
        options: Additional options (provider_options, generator_options, etc.).
        current_item: The current item being processed (set by engine).
    """

    selection: Selection
    options: dict[str, Any] = field(default_factory=dict)
    current_item: dict[str, Any] | None = None
