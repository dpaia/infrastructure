"""Tests for MultiGeneratorRunner."""

from typing import Any, Iterator

import pytest

from ee_bench_generator.interfaces import Generator, Provider
from ee_bench_generator.metadata import (
    Context,
    FieldDescriptor,
    GeneratorMetadata,
    ProviderMetadata,
    Selection,
)
from ee_bench_generator.multi_generator import GeneratorSpec, MultiGeneratorRunner


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
        self._prepare_count = 0

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
        self._prepare_count += 1

    def get_field(self, name: str, source: str, context: Context) -> Any:
        return f"value_for_{name}"

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:
        yield {"id": "item1"}
        yield {"id": "item2"}


class MockGenerator(Generator):
    """Mock generator for testing."""

    def __init__(
        self,
        name: str = "mock_generator",
        required_fields: list[FieldDescriptor] | None = None,
        prefix: str = "",
    ):
        self._name = name
        self._required_fields = required_fields or []
        self._prefix = prefix

    @property
    def metadata(self) -> GeneratorMetadata:
        return GeneratorMetadata(
            name=self._name,
            required_fields=self._required_fields,
        )

    def generate(
        self, provider: Provider, context: Context
    ) -> Iterator[dict[str, Any]]:
        gen_opts = context.options.get("generator_options", {})
        for item in provider.iter_items(context):
            context.current_item = item
            yield {
                "id": f"{self._prefix}{item['id']}",
                "generator": self._name,
                "dry_run": gen_opts.get("dry_run", False),
            }


def _make_selection() -> Selection:
    return Selection(resource="test", filters={})


class TestGeneratorSpec:
    def test_creates_with_defaults(self):
        gen = MockGenerator()
        spec = GeneratorSpec(name="test", generator=gen)
        assert spec.name == "test"
        assert spec.generator is gen
        assert spec.options == {}
        assert spec.output_config == {}

    def test_creates_with_options(self):
        gen = MockGenerator()
        spec = GeneratorSpec(
            name="test",
            generator=gen,
            options={"key": "value"},
            output_config={"format": "jsonl", "path": "out.jsonl"},
        )
        assert spec.options == {"key": "value"}
        assert spec.output_config == {"format": "jsonl", "path": "out.jsonl"}


class TestMultiGeneratorRunner:
    def test_runs_single_generator(self):
        fields = [FieldDescriptor("id", "dataset")]
        provider = MockProvider(provided_fields=fields)
        gen = MockGenerator(name="gen1", required_fields=fields, prefix="a_")

        spec = GeneratorSpec(name="gen1", generator=gen)
        runner = MultiGeneratorRunner(provider, [spec], defer_validation=True)

        results = runner.run_all(_make_selection())
        assert "gen1" in results
        assert len(results["gen1"]) == 2
        assert results["gen1"][0]["id"] == "a_item1"

    def test_runs_multiple_generators(self):
        fields = [FieldDescriptor("id", "dataset")]
        provider = MockProvider(provided_fields=fields)
        gen1 = MockGenerator(name="gen1", required_fields=fields, prefix="a_")
        gen2 = MockGenerator(name="gen2", required_fields=fields, prefix="b_")

        specs = [
            GeneratorSpec(name="first", generator=gen1),
            GeneratorSpec(name="second", generator=gen2),
        ]
        runner = MultiGeneratorRunner(provider, specs, defer_validation=True)

        results = runner.run_all(_make_selection())
        assert len(results) == 2
        assert results["first"][0]["id"] == "a_item1"
        assert results["second"][0]["id"] == "b_item1"

    def test_each_generator_gets_own_options(self):
        fields = [FieldDescriptor("id", "dataset")]
        provider = MockProvider(provided_fields=fields)
        gen1 = MockGenerator(name="gen1", required_fields=fields)
        gen2 = MockGenerator(name="gen2", required_fields=fields)

        specs = [
            GeneratorSpec(name="first", generator=gen1, options={"dry_run": True}),
            GeneratorSpec(name="second", generator=gen2, options={"dry_run": False}),
        ]
        runner = MultiGeneratorRunner(provider, specs, defer_validation=True)

        results = runner.run_all(_make_selection())
        assert results["first"][0]["dry_run"] is True
        assert results["second"][0]["dry_run"] is False

    def test_run_returns_iterators(self):
        fields = [FieldDescriptor("id", "dataset")]
        provider = MockProvider(provided_fields=fields)
        gen = MockGenerator(name="gen1", required_fields=fields)

        spec = GeneratorSpec(name="gen1", generator=gen)
        runner = MultiGeneratorRunner(provider, [spec], defer_validation=True)

        iterators = runner.run(_make_selection())
        assert "gen1" in iterators
        # Should be an iterator, not a list
        records = list(iterators["gen1"])
        assert len(records) == 2

    def test_generator_spec_options_override_run_options(self):
        """Generator-specific options should override run-level generator_options."""
        fields = [FieldDescriptor("id", "dataset")]
        provider = MockProvider(provided_fields=fields)
        gen = MockGenerator(name="gen1", required_fields=fields)

        spec = GeneratorSpec(
            name="gen1",
            generator=gen,
            options={"dry_run": True},  # spec-level option
        )
        runner = MultiGeneratorRunner(provider, [spec], defer_validation=True)

        # run-level option says dry_run=False, but spec says True
        results = runner.run_all(
            _make_selection(),
            generator_options={"dry_run": False},
        )
        # Spec-level should win
        assert results["gen1"][0]["dry_run"] is True

    def test_empty_specs_list(self):
        fields = [FieldDescriptor("id", "dataset")]
        provider = MockProvider(provided_fields=fields)
        runner = MultiGeneratorRunner(provider, [])

        results = runner.run_all(_make_selection())
        assert results == {}
