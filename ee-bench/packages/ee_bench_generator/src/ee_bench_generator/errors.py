"""Custom exceptions for ee_bench_generator."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ee_bench_generator.metadata import ValidationResult


class EEBenchError(Exception):
    """Base exception for ee_bench_generator."""


class PluginNotFoundError(EEBenchError):
    """Raised when a requested plugin is not found."""

    def __init__(self, plugin_type: str, name: str) -> None:
        self.plugin_type = plugin_type
        self.name = name
        super().__init__(f"{plugin_type} '{name}' not found")


class IncompatiblePluginsError(EEBenchError):
    """Raised when provider and generator are not compatible."""

    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        missing_names = [f.name for f in result.missing_required]
        super().__init__(
            f"Provider cannot satisfy generator requirements. "
            f"Missing required fields: {missing_names}"
        )


class ProviderError(EEBenchError):
    """Raised when a provider encounters an error."""


class GeneratorError(EEBenchError):
    """Raised when a generator encounters an error."""
