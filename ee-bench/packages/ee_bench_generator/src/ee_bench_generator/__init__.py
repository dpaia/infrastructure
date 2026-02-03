"""ee_bench_generator - Core framework for pluggable dataset generation.

This package provides the foundation for building dataset generators
with a provider/generator plugin architecture.

Example:
    >>> from ee_bench_generator import DatasetEngine, Selection
    >>> from ee_bench_generator import load_provider, load_generator
    >>>
    >>> # Load plugins
    >>> provider = load_provider("github_pull_requests")  # doctest: +SKIP
    >>> generator = load_generator("dpaia_jvm")  # doctest: +SKIP
    >>>
    >>> # Create engine and run
    >>> engine = DatasetEngine(provider, generator)  # doctest: +SKIP
    >>> selection = Selection(
    ...     resource="pull_requests",
    ...     filters={"repo": "org/repo", "pr_numbers": [42]}
    ... )  # doctest: +SKIP
    >>> for record in engine.run(selection):  # doctest: +SKIP
    ...     print(record)
"""

from ee_bench_generator.clock import now_iso8601_utc
from ee_bench_generator.engine import DatasetEngine
from ee_bench_generator.errors import (
    EEBenchError,
    GeneratorError,
    IncompatiblePluginsError,
    PluginNotFoundError,
    ProviderError,
)
from ee_bench_generator.interfaces import Generator, Provider
from ee_bench_generator.loader import (
    list_generators,
    list_providers,
    load_generator,
    load_provider,
)
from ee_bench_generator.matcher import validate_compatibility
from ee_bench_generator.metadata import (
    Context,
    FieldDescriptor,
    GeneratorMetadata,
    ProviderMetadata,
    Selection,
    ValidationResult,
)

__version__ = "0.1.0"

__all__ = [
    # Engine
    "DatasetEngine",
    # Interfaces
    "Provider",
    "Generator",
    # Metadata types
    "FieldDescriptor",
    "ProviderMetadata",
    "GeneratorMetadata",
    "ValidationResult",
    "Selection",
    "Context",
    # Loader functions
    "load_provider",
    "load_generator",
    "list_providers",
    "list_generators",
    # Matcher
    "validate_compatibility",
    # Clock
    "now_iso8601_utc",
    # Errors
    "EEBenchError",
    "PluginNotFoundError",
    "IncompatiblePluginsError",
    "ProviderError",
    "GeneratorError",
]
