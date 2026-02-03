"""Abstract base classes for Provider and Generator plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from ee_bench_generator.metadata import Context, GeneratorMetadata, ProviderMetadata


class Provider(ABC):
    """Abstract base class for data providers.

    Providers fetch data from external sources (e.g., GitHub, Jira) and
    expose it through a field-based interface. Each provider declares
    its capabilities via metadata.
    """

    @property
    @abstractmethod
    def metadata(self) -> ProviderMetadata:
        """Return metadata describing this provider's capabilities.

        Returns:
            ProviderMetadata declaring available fields and sources.
        """
        ...

    @abstractmethod
    def prepare(self, **options: Any) -> None:
        """Prepare the provider for use.

        Called before any data fetching. Use this to configure
        authentication, caching, rate limits, etc.

        Args:
            **options: Provider-specific configuration options.
        """
        ...

    @abstractmethod
    def get_field(self, name: str, source: str, context: Context) -> Any:
        """Retrieve a specific field value.

        Args:
            name: The field name to retrieve.
            source: The source to retrieve from.
            context: Current runtime context with selection and current item.

        Returns:
            The field value.

        Raises:
            ProviderError: If the field cannot be retrieved.
        """
        ...

    @abstractmethod
    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:
        """Iterate over selected items.

        Args:
            context: Runtime context containing selection criteria.

        Yields:
            Dictionary with basic item info (e.g., repo, number, etc.)
            that will be set as context.current_item.
        """
        ...


class Generator(ABC):
    """Abstract base class for dataset generators.

    Generators produce dataset records by requesting fields from
    providers and transforming them into the desired output format.
    """

    @property
    @abstractmethod
    def metadata(self) -> GeneratorMetadata:
        """Return metadata describing this generator's requirements.

        Returns:
            GeneratorMetadata declaring required and optional fields.
        """
        ...

    @abstractmethod
    def output_schema(self) -> dict[str, Any]:
        """Return JSON Schema for the output records.

        Returns:
            JSON Schema dictionary describing the output format.
        """
        ...

    @abstractmethod
    def generate(
        self, provider: Provider, context: Context
    ) -> Iterator[dict[str, Any]]:
        """Generate dataset records.

        Args:
            provider: The data provider to fetch fields from.
            context: Runtime context with selection and options.

        Yields:
            Dataset records as dictionaries.
        """
        ...
