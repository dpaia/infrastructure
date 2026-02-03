"""Tests for custom exceptions."""

import pytest

from ee_bench_generator.errors import (
    EEBenchError,
    GeneratorError,
    IncompatiblePluginsError,
    PluginNotFoundError,
    ProviderError,
)
from ee_bench_generator.metadata import FieldDescriptor, ValidationResult


class TestPluginNotFoundError:
    """Tests for PluginNotFoundError."""

    def test_stores_plugin_type_and_name(self):
        """Test that error stores plugin_type and name."""
        error = PluginNotFoundError("provider", "github_issues")

        assert error.plugin_type == "provider"
        assert error.name == "github_issues"

    def test_message_format(self):
        """Test error message format."""
        error = PluginNotFoundError("generator", "dpaia_jvm")

        assert "generator 'dpaia_jvm' not found" in str(error)

    def test_inherits_from_base(self):
        """Test that error inherits from EEBenchError."""
        error = PluginNotFoundError("provider", "test")
        assert isinstance(error, EEBenchError)


class TestIncompatiblePluginsError:
    """Tests for IncompatiblePluginsError."""

    def test_stores_validation_result(self):
        """Test that error stores the validation result."""
        result = ValidationResult(
            compatible=False,
            missing_required=[FieldDescriptor("patch", "pull_request")],
            missing_optional=[],
        )
        error = IncompatiblePluginsError(result)

        assert error.result is result

    def test_message_includes_missing_fields(self):
        """Test error message includes missing field names."""
        result = ValidationResult(
            compatible=False,
            missing_required=[
                FieldDescriptor("patch", "pull_request"),
                FieldDescriptor("description", "pull_request"),
            ],
            missing_optional=[],
        )
        error = IncompatiblePluginsError(result)

        message = str(error)
        assert "patch" in message
        assert "description" in message

    def test_inherits_from_base(self):
        """Test that error inherits from EEBenchError."""
        result = ValidationResult(
            compatible=False, missing_required=[], missing_optional=[]
        )
        error = IncompatiblePluginsError(result)
        assert isinstance(error, EEBenchError)


class TestProviderError:
    """Tests for ProviderError."""

    def test_can_be_raised(self):
        """Test that ProviderError can be raised and caught."""
        with pytest.raises(ProviderError) as exc_info:
            raise ProviderError("Failed to fetch data")

        assert "Failed to fetch data" in str(exc_info.value)

    def test_inherits_from_base(self):
        """Test that error inherits from EEBenchError."""
        error = ProviderError("test")
        assert isinstance(error, EEBenchError)


class TestGeneratorError:
    """Tests for GeneratorError."""

    def test_can_be_raised(self):
        """Test that GeneratorError can be raised and caught."""
        with pytest.raises(GeneratorError) as exc_info:
            raise GeneratorError("Failed to generate record")

        assert "Failed to generate record" in str(exc_info.value)

    def test_inherits_from_base(self):
        """Test that error inherits from EEBenchError."""
        error = GeneratorError("test")
        assert isinstance(error, EEBenchError)
