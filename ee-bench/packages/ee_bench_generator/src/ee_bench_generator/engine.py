"""Dataset generation engine."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator

from ee_bench_generator.errors import IncompatiblePluginsError
from ee_bench_generator.matcher import validate_compatibility
from ee_bench_generator.metadata import Context, Selection

if TYPE_CHECKING:
    from ee_bench_generator.interfaces import Generator, Provider


class DatasetEngine:
    """Orchestrates dataset generation by connecting providers and generators.

    The engine validates that the provider can satisfy the generator's
    requirements before starting generation.

    Example:
        >>> # Assuming provider and generator are properly implemented
        >>> engine = DatasetEngine(provider, generator)  # doctest: +SKIP
        >>> selection = Selection(
        ...     resource="pull_requests",
        ...     filters={"repo": "org/repo", "pr_numbers": [42]}
        ... )  # doctest: +SKIP
        >>> for record in engine.run(selection):  # doctest: +SKIP
        ...     print(record)
    """

    def __init__(self, provider: Provider, generator: Generator) -> None:
        """Initialize the engine with a provider and generator.

        Args:
            provider: The data provider to fetch fields from.
            generator: The generator that produces output records.

        Raises:
            IncompatiblePluginsError: If provider cannot satisfy generator requirements.
        """
        result = validate_compatibility(provider.metadata, generator.metadata)
        if not result.compatible:
            raise IncompatiblePluginsError(result)

        self.provider = provider
        self.generator = generator
        self._validation_result = result

    @property
    def validation_result(self):
        """Get the validation result from compatibility check.

        Returns:
            ValidationResult from provider/generator compatibility validation.
        """
        return self._validation_result

    def run(
        self, selection: Selection, **options: Any
    ) -> Iterator[dict[str, Any]]:
        """Run the dataset generation.

        Args:
            selection: Selection criteria for items to process.
            **options: Additional options including:
                - provider_options: Dict of options passed to provider.prepare()
                - generator_options: Dict of options passed to generator

        Yields:
            Dataset records as dictionaries.
        """
        context = Context(selection=selection, options=options)

        # Prepare the provider with its specific options
        provider_options = options.get("provider_options", {})
        self.provider.prepare(**provider_options)

        # Let the generator drive the iteration
        yield from self.generator.generate(self.provider, context)
