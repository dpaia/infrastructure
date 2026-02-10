"""MultiGeneratorRunner — runs multiple generators sequentially against the same provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from ee_bench_generator.engine import DatasetEngine
from ee_bench_generator.interfaces import Generator, Provider
from ee_bench_generator.metadata import Selection


@dataclass
class GeneratorSpec:
    """Specification for a single generator in a multi-generator run.

    Attributes:
        name: Unique instance identifier for this generator.
        generator: Instantiated Generator object.
        options: Generator-specific options dict.
        output_config: Output configuration (format, path).
    """

    name: str
    generator: Generator
    options: dict[str, Any] = field(default_factory=dict)
    output_config: dict[str, Any] = field(default_factory=dict)


class MultiGeneratorRunner:
    """Runs multiple generators sequentially against the same provider.

    Each generator gets its own ``DatasetEngine`` and produces its own output.
    The provider is shared (and ``prepare()``d once before the first generator).

    Args:
        provider: The shared data provider.
        specs: List of GeneratorSpec, one per generator to run.
        defer_validation: If True, defer compatibility validation until run().
    """

    def __init__(
        self,
        provider: Provider,
        specs: list[GeneratorSpec],
        *,
        defer_validation: bool = False,
    ) -> None:
        self.provider = provider
        self.specs = specs
        self._defer_validation = defer_validation

    def run(
        self, selection: Selection, **options: Any
    ) -> dict[str, Iterator[dict[str, Any]]]:
        """Run all generators and return iterators keyed by generator name.

        The caller is responsible for consuming the iterators and writing output.
        The provider is prepared once before the first generator runs.

        Args:
            selection: Selection criteria for items to process.
            **options: Additional options. ``provider_options`` is extracted
                and passed to ``provider.prepare()``.

        Returns:
            Dict mapping generator name to record iterator.
        """
        results: dict[str, Iterator[dict[str, Any]]] = {}

        for spec in self.specs:
            engine = DatasetEngine(
                self.provider,
                spec.generator,
                defer_validation=self._defer_validation,
            )
            # Merge generator-specific options
            run_options = {**options}
            run_options["generator_options"] = {
                **options.get("generator_options", {}),
                **spec.options,
            }
            results[spec.name] = engine.run(selection, **run_options)

        return results

    def run_all(
        self, selection: Selection, **options: Any
    ) -> dict[str, list[dict[str, Any]]]:
        """Run all generators and materialize all results.

        Convenience method that consumes all iterators and returns lists.

        Args:
            selection: Selection criteria for items to process.
            **options: Additional options.

        Returns:
            Dict mapping generator name to list of records.
        """
        iterators = self.run(selection, **options)
        return {name: list(it) for name, it in iterators.items()}
