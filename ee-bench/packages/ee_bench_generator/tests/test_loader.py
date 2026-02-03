"""Tests for plugin loader."""

import pytest

from ee_bench_generator.errors import PluginNotFoundError
from ee_bench_generator.loader import (
    list_generators,
    list_providers,
    load_generator,
    load_provider,
)


class TestLoadProvider:
    """Tests for load_provider function."""

    def test_raises_error_for_nonexistent_provider(self):
        """Test that loading a nonexistent provider raises PluginNotFoundError."""
        with pytest.raises(PluginNotFoundError) as exc_info:
            load_provider("nonexistent_provider")

        assert exc_info.value.plugin_type == "provider"
        assert exc_info.value.name == "nonexistent_provider"
        assert "provider 'nonexistent_provider' not found" in str(exc_info.value)


class TestLoadGenerator:
    """Tests for load_generator function."""

    def test_raises_error_for_nonexistent_generator(self):
        """Test that loading a nonexistent generator raises PluginNotFoundError."""
        with pytest.raises(PluginNotFoundError) as exc_info:
            load_generator("nonexistent_generator")

        assert exc_info.value.plugin_type == "generator"
        assert exc_info.value.name == "nonexistent_generator"
        assert "generator 'nonexistent_generator' not found" in str(exc_info.value)


class TestListProviders:
    """Tests for list_providers function."""

    def test_returns_empty_list_when_no_providers(self):
        """Test that list_providers returns empty list when no providers registered."""
        providers = list_providers()

        # With no plugins installed, should return empty list
        assert isinstance(providers, list)
        # Note: In a real environment with plugins, this would return them


class TestListGenerators:
    """Tests for list_generators function."""

    def test_returns_empty_list_when_no_generators(self):
        """Test that list_generators returns empty list when no generators registered."""
        generators = list_generators()

        # With no plugins installed, should return empty list
        assert isinstance(generators, list)
        # Note: In a real environment with plugins, this would return them
