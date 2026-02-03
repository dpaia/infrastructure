"""Plugin discovery and loading via entry points."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if sys.version_info >= (3, 12):
    from importlib.metadata import entry_points
else:
    from importlib.metadata import entry_points

from ee_bench_generator.errors import PluginNotFoundError

if TYPE_CHECKING:
    from ee_bench_generator.interfaces import Generator, Provider
    from ee_bench_generator.metadata import GeneratorMetadata, ProviderMetadata

PROVIDERS_GROUP = "ee_bench_generator.providers"
GENERATORS_GROUP = "ee_bench_generator.generators"


def _get_entry_points(group: str) -> dict[str, any]:
    """Get entry points for a specific group.

    Args:
        group: The entry point group name.

    Returns:
        Dictionary mapping entry point names to entry point objects.
    """
    eps = entry_points()
    if hasattr(eps, "select"):
        # Python 3.10+ / importlib_metadata 3.6+
        return {ep.name: ep for ep in eps.select(group=group)}
    else:
        # Older API returns dict-like
        return {ep.name: ep for ep in eps.get(group, [])}


def load_provider(name: str) -> Provider:
    """Load a provider plugin by name.

    Args:
        name: The provider name (entry point name).

    Returns:
        Instantiated Provider object.

    Raises:
        PluginNotFoundError: If the provider is not found.
    """
    providers = _get_entry_points(PROVIDERS_GROUP)
    if name not in providers:
        raise PluginNotFoundError("provider", name)

    provider_class = providers[name].load()
    return provider_class()


def load_generator(name: str) -> Generator:
    """Load a generator plugin by name.

    Args:
        name: The generator name (entry point name).

    Returns:
        Instantiated Generator object.

    Raises:
        PluginNotFoundError: If the generator is not found.
    """
    generators = _get_entry_points(GENERATORS_GROUP)
    if name not in generators:
        raise PluginNotFoundError("generator", name)

    generator_class = generators[name].load()
    return generator_class()


def list_providers() -> list[tuple[str, ProviderMetadata]]:
    """List all available provider plugins.

    Returns:
        List of (name, metadata) tuples for each registered provider.
    """
    providers = _get_entry_points(PROVIDERS_GROUP)
    result = []
    for name, ep in providers.items():
        provider_class = ep.load()
        # Instantiate to get metadata
        provider = provider_class()
        result.append((name, provider.metadata))
    return result


def list_generators() -> list[tuple[str, GeneratorMetadata]]:
    """List all available generator plugins.

    Returns:
        List of (name, metadata) tuples for each registered generator.
    """
    generators = _get_entry_points(GENERATORS_GROUP)
    result = []
    for name, ep in generators.items():
        generator_class = ep.load()
        # Instantiate to get metadata
        generator = generator_class()
        result.append((name, generator.metadata))
    return result
