"""Tests for DatasetEngine."""

from typing import Any, Iterator

import pytest

from ee_bench_generator.engine import DatasetEngine
from ee_bench_generator.errors import IncompatiblePluginsError
from ee_bench_generator.interfaces import Generator, Provider
from ee_bench_generator.metadata import (
    Context,
    FieldDescriptor,
    GeneratorMetadata,
    ProviderMetadata,
    Selection,
)


class MockProvider(Provider):
    """Mock provider for testing."""

    def __init__(
        self,
        name: str = "mock_provider",
        provided_fields: list[FieldDescriptor] | None = None,
    ):
        self._name = name
        self._provided_fields = provided_fields or []
        self._prepared = False
        self._prepare_options: dict[str, Any] = {}

    @property
    def metadata(self) -> ProviderMetadata:
        sources = list({f.source for f in self._provided_fields})
        return ProviderMetadata(
            name=self._name,
            sources=sources,
            provided_fields=self._provided_fields,
        )

    def prepare(self, **options: Any) -> None:
        self._prepared = True
        self._prepare_options = options

    def get_field(self, name: str, source: str, context: Context) -> Any:
        return f"value_for_{name}"

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:
        yield {"repo": "test/repo", "number": 1}
        yield {"repo": "test/repo", "number": 2}


class MockGenerator(Generator):
    """Mock generator for testing."""

    def __init__(
        self,
        name: str = "mock_generator",
        required_fields: list[FieldDescriptor] | None = None,
        optional_fields: list[FieldDescriptor] | None = None,
    ):
        self._name = name
        self._required_fields = required_fields or []
        self._optional_fields = optional_fields or []

    @property
    def metadata(self) -> GeneratorMetadata:
        return GeneratorMetadata(
            name=self._name,
            required_fields=self._required_fields,
            optional_fields=self._optional_fields,
        )

    def generate(
        self, provider: Provider, context: Context
    ) -> Iterator[dict[str, Any]]:
        for item in provider.iter_items(context):
            context.current_item = item
            yield {
                "id": f"{item['repo']}_{item['number']}",
                "description": provider.get_field("description", "pull_request", context),
            }


class TestDatasetEngine:
    """Tests for DatasetEngine class."""

    def test_creates_engine_with_compatible_plugins(self):
        """Test engine creation with compatible provider and generator."""
        provider = MockProvider(
            provided_fields=[
                FieldDescriptor("description", "pull_request"),
            ]
        )
        generator = MockGenerator(
            required_fields=[
                FieldDescriptor("description", "pull_request"),
            ]
        )

        engine = DatasetEngine(provider, generator)

        assert engine.provider is provider
        assert engine.generator is generator
        assert engine.validation_result.compatible is True

    def test_raises_error_with_incompatible_plugins(self):
        """Test engine raises error when plugins are incompatible."""
        provider = MockProvider(provided_fields=[])
        generator = MockGenerator(
            required_fields=[
                FieldDescriptor("description", "pull_request"),
            ]
        )

        with pytest.raises(IncompatiblePluginsError) as exc_info:
            DatasetEngine(provider, generator)

        assert "description" in str(exc_info.value)
        assert exc_info.value.result.compatible is False

    def test_run_prepares_provider(self):
        """Test that run() prepares the provider with options."""
        provider = MockProvider(
            provided_fields=[
                FieldDescriptor("description", "pull_request"),
            ]
        )
        generator = MockGenerator(
            required_fields=[
                FieldDescriptor("description", "pull_request"),
            ]
        )
        engine = DatasetEngine(provider, generator)
        selection = Selection(resource="pull_requests", filters={})

        # Consume the iterator to trigger preparation
        list(engine.run(selection, provider_options={"token": "abc"}))

        assert provider._prepared is True
        assert provider._prepare_options == {"token": "abc"}

    def test_run_yields_records(self):
        """Test that run() yields records from generator."""
        provider = MockProvider(
            provided_fields=[
                FieldDescriptor("description", "pull_request"),
            ]
        )
        generator = MockGenerator(
            required_fields=[
                FieldDescriptor("description", "pull_request"),
            ]
        )
        engine = DatasetEngine(provider, generator)
        selection = Selection(resource="pull_requests", filters={})

        records = list(engine.run(selection))

        assert len(records) == 2
        assert records[0]["id"] == "test/repo_1"
        assert records[1]["id"] == "test/repo_2"

    def test_run_passes_context_to_generator(self):
        """Test that run() creates proper context for generator."""

        class ContextCapturingGenerator(MockGenerator):
            captured_context: Context | None = None

            def generate(
                self, provider: Provider, context: Context
            ) -> Iterator[dict[str, Any]]:
                self.captured_context = context
                yield {}

        provider = MockProvider(
            provided_fields=[
                FieldDescriptor("description", "pull_request"),
            ]
        )
        generator = ContextCapturingGenerator(
            required_fields=[
                FieldDescriptor("description", "pull_request"),
            ]
        )
        engine = DatasetEngine(provider, generator)
        selection = Selection(
            resource="pull_requests",
            filters={"repo": "org/repo"},
            limit=10,
        )

        list(engine.run(selection, generator_options={"version": "1"}))

        assert generator.captured_context is not None
        assert generator.captured_context.selection is selection
        assert generator.captured_context.options["generator_options"] == {"version": "1"}

    def test_validation_result_accessible(self):
        """Test that validation result is accessible after creation."""
        provider = MockProvider(
            provided_fields=[
                FieldDescriptor("description", "pull_request"),
                FieldDescriptor("patch", "pull_request"),
            ]
        )
        generator = MockGenerator(
            required_fields=[
                FieldDescriptor("description", "pull_request"),
            ],
            optional_fields=[
                FieldDescriptor("title", "pull_request", required=False),
            ],
        )

        engine = DatasetEngine(provider, generator)

        assert engine.validation_result.compatible is True
        assert len(engine.validation_result.missing_optional) == 1
