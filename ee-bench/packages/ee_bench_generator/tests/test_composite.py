"""Tests for CompositeProvider."""

from typing import Any, Iterator

import pytest

from ee_bench_generator.composite import (
    CompositeProvider,
    CompositeProviderConfigError,
    CyclicDependencyError,
    _build_dependency_graph,
    _topological_sort,
)
from ee_bench_generator.errors import ProviderError
from ee_bench_generator.interfaces import Provider
from ee_bench_generator.metadata import (
    Context,
    FieldDescriptor,
    ProviderMetadata,
    Selection,
)


class MockProvider(Provider):
    """Mock provider for testing."""

    def __init__(
        self,
        name: str = "mock_provider",
        provided_fields: list[FieldDescriptor] | None = None,
        items: list[dict[str, Any]] | None = None,
        field_values: dict[str, Any] | None = None,
    ):
        self._name = name
        self._provided_fields = provided_fields or []
        self._items = items or []
        self._field_values = field_values or {}
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
        # If field_values has a callable, call it with context
        key = f"{name}:{source}"
        if key in self._field_values:
            val = self._field_values[key]
            if callable(val):
                return val(context)
            return val
        if name in self._field_values:
            val = self._field_values[name]
            if callable(val):
                return val(context)
            return val
        # Fall back to current_item if available
        if context.current_item and name in context.current_item:
            return context.current_item[name]
        return f"value_for_{name}"

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:
        yield from self._items


def _make_selection() -> Selection:
    return Selection(resource="test", filters={})


def _make_context() -> Context:
    return Context(selection=_make_selection())


class TestBuildDependencyGraph:
    def test_no_dependencies(self):
        configs = [
            {"name": "a"},
            {"name": "b"},
        ]
        graph = _build_dependency_graph(configs)
        assert graph == {"a": [], "b": []}

    def test_simple_dependency(self):
        configs = [
            {"name": "primary"},
            {
                "name": "enricher",
                "item_mapping": {
                    "owner": "{{ providers.primary.repo }}",
                },
            },
        ]
        graph = _build_dependency_graph(configs)
        assert graph["primary"] == []
        assert graph["enricher"] == ["primary"]

    def test_multiple_dependencies(self):
        configs = [
            {"name": "a"},
            {"name": "b"},
            {
                "name": "c",
                "item_mapping": {
                    "x": "{{ providers.a.field1 }}",
                    "y": "{{ providers.b.field2 }}",
                },
            },
        ]
        graph = _build_dependency_graph(configs)
        assert set(graph["c"]) == {"a", "b"}


class TestTopologicalSort:
    def test_simple_chain(self):
        graph = {"a": [], "b": ["a"], "c": ["b"]}
        order = _topological_sort(graph)
        assert order.index("a") < order.index("b") < order.index("c")

    def test_no_dependencies(self):
        graph = {"a": [], "b": [], "c": []}
        order = _topological_sort(graph)
        assert set(order) == {"a", "b", "c"}

    def test_detects_cycle(self):
        graph = {"a": ["b"], "b": ["a"]}
        with pytest.raises(CyclicDependencyError):
            _topological_sort(graph)

    def test_detects_three_node_cycle(self):
        graph = {"a": ["b"], "b": ["c"], "c": ["a"]}
        with pytest.raises(CyclicDependencyError):
            _topological_sort(graph)


class TestCompositeProviderConfig:
    def test_requires_at_least_one_provider(self):
        with pytest.raises(CompositeProviderConfigError, match="At least one"):
            CompositeProvider([])

    def test_requires_primary_role(self):
        prov = MockProvider(name="test")
        with pytest.raises(CompositeProviderConfigError, match="role 'primary'"):
            CompositeProvider([{"name": "test", "provider": prov}])

    def test_rejects_duplicate_names(self):
        prov1 = MockProvider(name="test")
        prov2 = MockProvider(name="test")
        with pytest.raises(CompositeProviderConfigError, match="Duplicate"):
            CompositeProvider([
                {"name": "dup", "provider": prov1, "role": "primary"},
                {"name": "dup", "provider": prov2},
            ])

    def test_rejects_multiple_primaries(self):
        prov1 = MockProvider(name="p1")
        prov2 = MockProvider(name="p2")
        with pytest.raises(CompositeProviderConfigError, match="multiple"):
            CompositeProvider([
                {"name": "a", "provider": prov1, "role": "primary"},
                {"name": "b", "provider": prov2, "role": "primary"},
            ])

    def test_accepts_valid_config(self):
        prov = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("repo", "dataset")],
        )
        composite = CompositeProvider([
            {"name": "main", "provider": prov, "role": "primary"},
        ])
        assert composite.primary is prov


class TestCompositeProviderMetadata:
    def test_single_provider_metadata(self):
        prov = MockProvider(
            name="test",
            provided_fields=[
                FieldDescriptor("repo", "dataset"),
                FieldDescriptor("pr_number", "dataset"),
            ],
        )
        composite = CompositeProvider([
            {"name": "main", "provider": prov, "role": "primary"},
        ])
        meta = composite.metadata
        assert meta.name == "composite"
        assert len(meta.provided_fields) == 2
        assert meta.can_provide("repo", "dataset")

    def test_merged_metadata_from_multiple_providers(self):
        prov1 = MockProvider(
            name="hf",
            provided_fields=[FieldDescriptor("repo", "dataset")],
        )
        prov2 = MockProvider(
            name="gh",
            provided_fields=[FieldDescriptor("patch", "pull_request")],
        )
        composite = CompositeProvider([
            {"name": "data", "provider": prov1, "role": "primary"},
            {"name": "prs", "provider": prov2},
        ])
        meta = composite.metadata
        assert meta.can_provide("repo", "dataset")
        assert meta.can_provide("patch", "pull_request")

    def test_deduplicates_fields(self):
        """If two providers declare the same (name, source), only one appears."""
        fd = FieldDescriptor("repo", "dataset")
        prov1 = MockProvider(name="p1", provided_fields=[fd])
        prov2 = MockProvider(name="p2", provided_fields=[fd])
        composite = CompositeProvider([
            {"name": "a", "provider": prov1, "role": "primary"},
            {"name": "b", "provider": prov2},
        ])
        meta = composite.metadata
        repo_fields = [f for f in meta.provided_fields if f.name == "repo"]
        assert len(repo_fields) == 1


class TestCompositeProviderPrepare:
    def test_prepares_all_providers_with_keyed_options(self):
        prov1 = MockProvider(name="hf", provided_fields=[FieldDescriptor("repo", "dataset")])
        prov2 = MockProvider(name="gh", provided_fields=[FieldDescriptor("patch", "pull_request")])
        composite = CompositeProvider([
            {"name": "data", "provider": prov1, "role": "primary"},
            {"name": "prs", "provider": prov2},
        ])

        composite.prepare(data={"dataset": "test"}, prs={"token": "abc"})

        assert prov1._prepared
        assert prov1._prepare_options == {"dataset": "test"}
        assert prov2._prepared
        assert prov2._prepare_options == {"token": "abc"}

    def test_flat_options_go_to_primary(self):
        prov1 = MockProvider(name="hf", provided_fields=[FieldDescriptor("repo", "dataset")])
        prov2 = MockProvider(name="gh", provided_fields=[FieldDescriptor("patch", "pull_request")])
        composite = CompositeProvider([
            {"name": "data", "provider": prov1, "role": "primary"},
            {"name": "prs", "provider": prov2},
        ])

        composite.prepare(dataset="test", split="train")

        assert prov1._prepared
        assert prov1._prepare_options == {"dataset": "test", "split": "train"}
        assert prov2._prepared
        assert prov2._prepare_options == {}


class TestCompositeProviderIterItems:
    def test_delegates_to_primary(self):
        items = [{"id": 1}, {"id": 2}, {"id": 3}]
        prov = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("id", "dataset")],
            items=items,
        )
        composite = CompositeProvider([
            {"name": "main", "provider": prov, "role": "primary"},
        ])

        ctx = _make_context()
        result = list(composite.iter_items(ctx))
        assert result == items


class TestCompositeProviderGetField:
    def test_get_field_from_primary(self):
        prov = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("repo", "dataset")],
            field_values={"repo": "django/django"},
            items=[{"instance_id": "test"}],
        )
        composite = CompositeProvider([
            {"name": "main", "provider": prov, "role": "primary"},
        ])

        ctx = _make_context()
        # Advance to first item
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        value = composite.get_field("repo", "dataset", ctx)
        assert value == "django/django"

    def test_get_field_from_enrichment_with_item_mapping(self):
        """Test that enrichment provider gets a mapped context based on primary fields."""
        primary = MockProvider(
            name="hf",
            provided_fields=[
                FieldDescriptor("repo", "dataset"),
                FieldDescriptor("pr_number", "dataset"),
            ],
            field_values={"repo": "django/django", "pr_number": 42},
            items=[{"instance_id": "django__django-42"}],
        )

        # Enrichment provider returns patch based on its mapped context
        enrichment = MockProvider(
            name="gh",
            provided_fields=[FieldDescriptor("patch", "pull_request")],
            field_values={
                "patch": lambda ctx: f"patch_for_{ctx.current_item.get('owner')}/{ctx.current_item.get('number')}",
            },
        )

        composite = CompositeProvider([
            {"name": "data", "provider": primary, "role": "primary"},
            {
                "name": "prs",
                "provider": enrichment,
                "item_mapping": {
                    "owner": "{{ providers.data.repo | split('/') | first }}",
                    "repo": "{{ providers.data.repo | split('/') | last }}",
                    "number": "{{ providers.data.pr_number }}",
                },
            },
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        patch = composite.get_field("patch", "pull_request", ctx)
        assert patch == "patch_for_django/42"

    def test_field_caching_per_item(self):
        """Fields are cached per item — same field is only fetched once."""
        call_count = 0

        def counting_field(ctx):
            nonlocal call_count
            call_count += 1
            return "value"

        prov = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("expensive", "dataset")],
            field_values={"expensive": counting_field},
            items=[{"id": 1}],
        )
        composite = CompositeProvider([
            {"name": "main", "provider": prov, "role": "primary"},
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        # Get field twice — should only call provider once
        composite.get_field("expensive", "dataset", ctx)
        composite.get_field("expensive", "dataset", ctx)
        assert call_count == 1

    def test_cache_cleared_between_items(self):
        """Cache is cleared when iter_items advances to next item."""
        call_count = 0

        def counting_field(ctx):
            nonlocal call_count
            call_count += 1
            return f"value_{call_count}"

        prov = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("field", "dataset")],
            field_values={"field": counting_field},
            items=[{"id": 1}, {"id": 2}],
        )
        composite = CompositeProvider([
            {"name": "main", "provider": prov, "role": "primary"},
        ])

        ctx = _make_context()
        for item in composite.iter_items(ctx):
            ctx.current_item = item
            composite.get_field("field", "dataset", ctx)

        # Each item should trigger a fresh call
        assert call_count == 2

    def test_raises_for_unknown_field(self):
        prov = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("repo", "dataset")],
            items=[{"id": 1}],
        )
        composite = CompositeProvider([
            {"name": "main", "provider": prov, "role": "primary"},
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        with pytest.raises(ProviderError, match="No provider can supply"):
            composite.get_field("nonexistent", "dataset", ctx)

    def test_get_field_source_less_resolves(self):
        """get_field with empty source resolves by name."""
        prov = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("repo", "dataset")],
            field_values={"repo": "django/django"},
            items=[{"id": 1}],
        )
        composite = CompositeProvider([
            {"name": "main", "provider": prov, "role": "primary"},
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        value = composite.get_field("repo", "", ctx)
        assert value == "django/django"

    def test_get_field_source_less_prefers_enrichment(self):
        """Later provider in dependency order wins for source-less lookup."""
        primary = MockProvider(
            name="hf",
            provided_fields=[FieldDescriptor("repo", "dataset")],
            field_values={"repo": "primary_repo"},
            items=[{"id": 1}],
        )
        enrichment = MockProvider(
            name="gh",
            provided_fields=[FieldDescriptor("repo", "enriched")],
            field_values={"repo": "enriched_repo"},
        )
        composite = CompositeProvider([
            {"name": "data", "provider": primary, "role": "primary"},
            {"name": "prs", "provider": enrichment},
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        # Enrichment provider comes later in dependency order and overrides
        value = composite.get_field("repo", "", ctx)
        assert value == "enriched_repo"

    def test_get_field_source_less_raises_for_unknown(self):
        """get_field with empty source raises for unknown field name."""
        prov = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("repo", "dataset")],
            items=[{"id": 1}],
        )
        composite = CompositeProvider([
            {"name": "main", "provider": prov, "role": "primary"},
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        with pytest.raises(ProviderError, match="source-less lookup"):
            composite.get_field("nonexistent", "", ctx)

    def test_get_field_source_less_caches(self):
        """Two calls with empty source only fetch once."""
        call_count = 0

        def counting_field(ctx):
            nonlocal call_count
            call_count += 1
            return "value"

        prov = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("expensive", "dataset")],
            field_values={"expensive": counting_field},
            items=[{"id": 1}],
        )
        composite = CompositeProvider([
            {"name": "main", "provider": prov, "role": "primary"},
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        composite.get_field("expensive", "", ctx)
        composite.get_field("expensive", "", ctx)
        assert call_count == 1


class TestCompositeProviderChaining:
    def test_three_provider_chain(self):
        """Test A -> B -> C chaining where C depends on B which depends on A."""
        provider_a = MockProvider(
            name="source_a",
            provided_fields=[
                FieldDescriptor("project_id", "source"),
            ],
            field_values={"project_id": "PROJ-123"},
            items=[{"id": "item1"}],
        )

        provider_b = MockProvider(
            name="source_b",
            provided_fields=[
                FieldDescriptor("ticket_url", "tracker"),
            ],
            field_values={
                "ticket_url": lambda ctx: f"https://jira.example.com/{ctx.current_item.get('project')}",
            },
        )

        provider_c = MockProvider(
            name="source_c",
            provided_fields=[
                FieldDescriptor("enriched_data", "enriched"),
            ],
            field_values={
                "enriched_data": lambda ctx: f"data_from_{ctx.current_item.get('url')}",
            },
        )

        composite = CompositeProvider([
            {"name": "a", "provider": provider_a, "role": "primary"},
            {
                "name": "b",
                "provider": provider_b,
                "item_mapping": {
                    "project": "{{ providers.a.project_id }}",
                },
            },
            {
                "name": "c",
                "provider": provider_c,
                "item_mapping": {
                    "url": "{{ providers.b.ticket_url }}",
                },
            },
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        # Field from A
        assert composite.get_field("project_id", "source", ctx) == "PROJ-123"

        # Field from B (depends on A)
        ticket = composite.get_field("ticket_url", "tracker", ctx)
        assert ticket == "https://jira.example.com/PROJ-123"

        # Field from C (depends on B which depends on A)
        enriched = composite.get_field("enriched_data", "enriched", ctx)
        assert enriched == "data_from_https://jira.example.com/PROJ-123"

    def test_cyclic_dependency_detected(self):
        prov_a = MockProvider(name="a", provided_fields=[FieldDescriptor("x", "s")])
        prov_b = MockProvider(name="b", provided_fields=[FieldDescriptor("y", "s")])

        with pytest.raises(CyclicDependencyError):
            CompositeProvider([
                {
                    "name": "a",
                    "provider": prov_a,
                    "role": "primary",
                    "item_mapping": {"x": "{{ providers.b.y }}"},
                },
                {
                    "name": "b",
                    "provider": prov_b,
                    "item_mapping": {"y": "{{ providers.a.x }}"},
                },
            ])
