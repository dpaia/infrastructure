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


class WildcardProvider(Provider):
    """Mock wildcard provider for testing."""

    def __init__(
        self,
        name: str = "wildcard",
        field_values: dict[str, Any] | None = None,
        discovered_fields: set[str] | None = None,
    ):
        self._name = name
        self._field_values = field_values or {}
        self._discovered_fields = discovered_fields or set()

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name=self._name,
            sources=["pull_request"],
            provided_fields=[],
            wildcard=True,
        )

    def prepare(self, **options: Any) -> None:
        pass

    def get_field(self, name: str, source: str, context: Context) -> Any:
        return self._field_values.get(name, "")

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:
        raise NotImplementedError

    def get_discovered_field_names(self) -> set[str]:
        return self._discovered_fields


class TestCompositeProviderWildcard:
    def test_wildcard_provider_resolves_unknown_field(self):
        """Fields not declared by any provider are routed to wildcard provider."""
        primary = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("repo", "dataset")],
            field_values={"repo": "django/django"},
            items=[{"id": 1}],
        )
        wildcard = WildcardProvider(
            field_values={"custom_field": "custom_value"},
        )
        composite = CompositeProvider([
            {"name": "main", "provider": primary, "role": "primary"},
            {"name": "wc", "provider": wildcard},
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        # Known field from primary
        assert composite.get_field("repo", "dataset", ctx) == "django/django"
        # Unknown field resolved by wildcard
        assert composite.get_field("custom_field", "", ctx) == "custom_value"

    def test_explicit_fields_override_wildcard(self):
        """Explicit field declarations always win over wildcard."""
        primary = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("repo", "dataset")],
            field_values={"repo": "primary_repo"},
            items=[{"id": 1}],
        )
        wildcard = WildcardProvider(
            field_values={"repo": "wildcard_repo"},
        )
        composite = CompositeProvider([
            {"name": "main", "provider": primary, "role": "primary"},
            {"name": "wc", "provider": wildcard},
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        # Primary's explicit field wins
        assert composite.get_field("repo", "", ctx) == "primary_repo"

    def test_composite_metadata_has_wildcard_flag(self):
        """Composite metadata reflects wildcard from sub-providers."""
        primary = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("repo", "dataset")],
            items=[{"id": 1}],
        )
        wildcard = WildcardProvider()
        composite = CompositeProvider([
            {"name": "main", "provider": primary, "role": "primary"},
            {"name": "wc", "provider": wildcard},
        ])
        assert composite.metadata.wildcard is True

    def test_no_wildcard_no_flag(self):
        """Composite without wildcard providers has wildcard=False."""
        primary = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("repo", "dataset")],
            items=[{"id": 1}],
        )
        composite = CompositeProvider([
            {"name": "main", "provider": primary, "role": "primary"},
        ])
        assert composite.metadata.wildcard is False

    def test_get_extra_fields(self):
        """get_extra_fields collects dynamically-discovered fields."""
        primary = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("repo", "dataset")],
            field_values={"repo": "django/django"},
            items=[{"id": 1}],
        )
        wildcard = WildcardProvider(
            field_values={
                "dynamic_a": "val_a",
                "dynamic_b": "val_b",
                "repo": "should_not_appear",  # already in routing table
            },
            discovered_fields={"dynamic_a", "dynamic_b", "repo"},
        )
        composite = CompositeProvider([
            {"name": "main", "provider": primary, "role": "primary"},
            {"name": "wc", "provider": wildcard},
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        extras = composite.get_extra_fields(ctx)
        # Only fields NOT in the routing table
        assert "dynamic_a" in extras
        assert "dynamic_b" in extras
        assert extras["dynamic_a"] == "val_a"
        assert extras["dynamic_b"] == "val_b"
        # "repo" is in the routing table so should not appear
        assert "repo" not in extras

    def test_get_extra_fields_empty_without_wildcard(self):
        """get_extra_fields returns empty when no wildcard providers."""
        primary = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("repo", "dataset")],
            items=[{"id": 1}],
        )
        composite = CompositeProvider([
            {"name": "main", "provider": primary, "role": "primary"},
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        assert composite.get_extra_fields(ctx) == {}

    def test_wildcard_provider_with_item_mapping(self):
        """Wildcard provider receives mapped context through item_mapping."""
        primary = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("description", "pull_request")],
            field_values={"description": "body text with <!--METADATA\nfoo:bar\nMETADATA-->"},
            items=[{"id": 1}],
        )
        wildcard = WildcardProvider(
            field_values={"some_meta_field": "meta_value"},
        )
        composite = CompositeProvider([
            {"name": "main", "provider": primary, "role": "primary"},
            {
                "name": "wc",
                "provider": wildcard,
                "item_mapping": {
                    "text": "{{ providers.main.description }}",
                },
            },
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        assert composite.get_field("some_meta_field", "", ctx) == "meta_value"


class TestTopologicalSortDeclarationOrder:
    def test_preserves_declaration_order(self):
        """Independent providers sorted by spec (declaration) order."""
        graph = {"a": [], "b": [], "c": []}
        order = _topological_sort(graph, declaration_order=["c", "a", "b"])
        assert order == ["c", "a", "b"]

    def test_respects_dependencies_over_declaration(self):
        """Dependencies override declaration order."""
        graph = {"a": ["b"], "b": [], "c": []}
        order = _topological_sort(graph, declaration_order=["a", "b", "c"])
        assert order.index("b") < order.index("a")

    def test_mixed_independent_and_dependent(self):
        """Dependent nodes come after deps, independent by declaration."""
        graph = {"x": [], "y": ["x"], "z": []}
        order = _topological_sort(graph, declaration_order=["z", "x", "y"])
        # z and x are independent; z is declared first
        # y depends on x so comes after x
        assert order.index("x") < order.index("y")
        assert order[0] == "z"


class NoneReturningProvider(Provider):
    """Mock provider that returns None for specified fields."""

    def __init__(
        self,
        name: str = "none_provider",
        provided_fields: list[FieldDescriptor] | None = None,
        none_fields: set[str] | None = None,
        field_values: dict[str, Any] | None = None,
    ):
        self._name = name
        self._provided_fields = provided_fields or []
        self._none_fields = none_fields or set()
        self._field_values = field_values or {}

    @property
    def metadata(self) -> ProviderMetadata:
        sources = list({f.source for f in self._provided_fields})
        return ProviderMetadata(
            name=self._name,
            sources=sources,
            provided_fields=self._provided_fields,
        )

    def prepare(self, **options: Any) -> None:
        pass

    def get_field(self, name: str, source: str, context: Context) -> Any:
        if name in self._none_fields:
            return None
        if name in self._field_values:
            val = self._field_values[name]
            if callable(val):
                return val(context)
            return val
        if context.current_item and name in context.current_item:
            return context.current_item[name]
        return f"value_for_{name}"

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:
        raise NotImplementedError


class TestFieldChainFallback:
    def test_field_chain_fallback_on_none(self):
        """Provider returns None, previous provider in chain used."""
        primary = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("data", "s")],
            field_values={"data": "primary_value"},
            items=[{"id": 1}],
        )
        # First enrichment: always returns a value
        first = MockProvider(
            name="first",
            provided_fields=[FieldDescriptor("data", "s")],
            field_values={"data": "first_value"},
        )
        # Second enrichment: returns None → should fall back to first
        second = NoneReturningProvider(
            name="second",
            provided_fields=[FieldDescriptor("data", "s")],
            none_fields={"data"},
        )
        composite = CompositeProvider([
            {"name": "primary", "provider": primary, "role": "primary"},
            {"name": "first", "provider": first},
            {"name": "second", "provider": second},
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        value = composite.get_field("data", "", ctx)
        assert value == "first_value"

    def test_field_chain_single_provider_no_fallback(self):
        """Single provider, no None check (backward compat)."""
        primary = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("data", "s")],
            field_values={"data": "the_value"},
            items=[{"id": 1}],
        )
        composite = CompositeProvider([
            {"name": "primary", "provider": primary, "role": "primary"},
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        value = composite.get_field("data", "", ctx)
        assert value == "the_value"

    def test_field_chain_all_none_falls_to_wildcard(self):
        """All chain providers return None, wildcard used."""
        primary = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("repo", "dataset")],
            items=[{"id": 1}],
        )
        # Two providers both return None for "data"
        prov_a = NoneReturningProvider(
            name="a",
            provided_fields=[FieldDescriptor("data", "s")],
            none_fields={"data"},
        )
        prov_b = NoneReturningProvider(
            name="b",
            provided_fields=[FieldDescriptor("data", "s")],
            none_fields={"data"},
        )
        wildcard = WildcardProvider(field_values={"data": "wildcard_value"})

        composite = CompositeProvider([
            {"name": "primary", "provider": primary, "role": "primary"},
            {"name": "a", "provider": prov_a},
            {"name": "b", "provider": prov_b},
            {"name": "wc", "provider": wildcard},
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        value = composite.get_field("data", "", ctx)
        assert value == "wildcard_value"

    def test_field_chain_last_wins_when_all_return_values(self):
        """Last provider's value used when all return non-None."""
        primary = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("data", "s")],
            field_values={"data": "primary_value"},
            items=[{"id": 1}],
        )
        first = MockProvider(
            name="first",
            provided_fields=[FieldDescriptor("data", "s")],
            field_values={"data": "first_value"},
        )
        second = MockProvider(
            name="second",
            provided_fields=[FieldDescriptor("data", "s")],
            field_values={"data": "second_value"},
        )
        composite = CompositeProvider([
            {"name": "primary", "provider": primary, "role": "primary"},
            {"name": "first", "provider": first},
            {"name": "second", "provider": second},
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        value = composite.get_field("data", "", ctx)
        assert value == "second_value"


class TestFieldsNamespace:
    def test_fields_namespace_in_jinja2(self):
        """{{ fields.X }} resolves from upstream provider."""
        primary = MockProvider(
            name="primary",
            provided_fields=[
                FieldDescriptor("data", "s"),
                FieldDescriptor("label", "s"),
            ],
            field_values={"data": "hello", "label": "world"},
            items=[{"id": 1}],
        )
        enrichment = MockProvider(
            name="enrichment",
            provided_fields=[FieldDescriptor("combined", "s")],
            field_values={
                "combined": lambda ctx: f"{ctx.current_item.get('d')}_{ctx.current_item.get('l')}",
            },
        )
        composite = CompositeProvider([
            {"name": "primary", "provider": primary, "role": "primary"},
            {
                "name": "enrichment",
                "provider": enrichment,
                "item_mapping": {
                    "d": "{{ fields.data }}",
                    "l": "{{ fields.label }}",
                },
            },
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        value = composite.get_field("combined", "", ctx)
        assert value == "hello_world"

    def test_fields_namespace_excludes_current_provider(self):
        """{{ fields.X }} in provider B resolves from provider A (upstream), not B itself."""
        primary = MockProvider(
            name="primary",
            provided_fields=[FieldDescriptor("value", "s")],
            field_values={"value": "from_primary"},
            items=[{"id": 1}],
        )
        # Provider A provides "value" with enrichment
        prov_a = MockProvider(
            name="a",
            provided_fields=[FieldDescriptor("value", "s")],
            field_values={"value": lambda ctx: f"a_{ctx.current_item.get('v', '')}"},
        )
        # Provider B also provides "value" and uses {{ fields.value }}
        # which should resolve from A (upstream), not from B itself
        prov_b = MockProvider(
            name="b",
            provided_fields=[FieldDescriptor("value", "s")],
            field_values={"value": lambda ctx: f"b_{ctx.current_item.get('v', '')}"},
        )
        composite = CompositeProvider([
            {"name": "primary", "provider": primary, "role": "primary"},
            {
                "name": "a",
                "provider": prov_a,
                "item_mapping": {
                    "v": "{{ fields.value }}",
                },
            },
            {
                "name": "b",
                "provider": prov_b,
                "item_mapping": {
                    "v": "{{ fields.value }}",
                },
            },
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        # get_field("value", "") goes to chain: primary, a, b
        # b is tried first (last in chain): b gets fields.value -> resolves from a
        # a gets fields.value -> resolves from primary -> "from_primary"
        # a returns "a_from_primary"
        # b gets "a_from_primary" and returns "b_a_from_primary"
        value = composite.get_field("value", "", ctx)
        assert value == "b_a_from_primary"


class RequiredInputsProvider(Provider):
    """Mock provider that declares required_inputs."""

    def __init__(
        self,
        name: str = "ri_provider",
        provided_fields: list[FieldDescriptor] | None = None,
        required_inputs: list[FieldDescriptor] | None = None,
        field_values: dict[str, Any] | None = None,
    ):
        self._name = name
        self._provided_fields = provided_fields or []
        self._required_inputs = required_inputs or []
        self._field_values = field_values or {}

    @property
    def metadata(self) -> ProviderMetadata:
        sources = list({f.source for f in self._provided_fields})
        return ProviderMetadata(
            name=self._name,
            sources=sources,
            provided_fields=self._provided_fields,
            required_inputs=self._required_inputs,
        )

    def prepare(self, **options: Any) -> None:
        pass

    def get_field(self, name: str, source: str, context: Context) -> Any:
        if name in self._field_values:
            val = self._field_values[name]
            if callable(val):
                return val(context)
            return val
        if context.current_item and name in context.current_item:
            return context.current_item[name]
        return f"value_for_{name}"

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:
        raise NotImplementedError


class TestRequiredInputsAutoWiring:
    def test_auto_wires_required_input_from_upstream(self):
        """required_inputs are resolved from upstream and merged into mapped_item."""
        primary = MockProvider(
            name="primary",
            provided_fields=[
                FieldDescriptor("repo_tree", "repository"),
                FieldDescriptor("build_system", "dataset"),
            ],
            field_values={"repo_tree": ["build.gradle", "src/main/java/App.java"],
                          "build_system": "gradle"},
            items=[{"id": 1}],
        )
        enrichment = RequiredInputsProvider(
            name="enricher",
            provided_fields=[FieldDescriptor("result", "")],
            required_inputs=[
                FieldDescriptor(name="repo_tree", required=True),
            ],
            field_values={
                "result": lambda ctx: f"tree_len={len(ctx.current_item.get('repo_tree', []))}",
            },
        )
        composite = CompositeProvider([
            {"name": "data", "provider": primary, "role": "primary"},
            {
                "name": "enricher",
                "provider": enrichment,
                "item_mapping": {
                    "build_system": "{{ providers.data.build_system }}",
                },
            },
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        result = composite.get_field("result", "", ctx)
        assert result == "tree_len=2"

    def test_item_mapping_overrides_auto_wiring(self):
        """Explicit item_mapping takes precedence over auto-wiring."""
        primary = MockProvider(
            name="primary",
            provided_fields=[
                FieldDescriptor("repo_tree", "repository"),
            ],
            field_values={"repo_tree": ["file1", "file2", "file3"]},
            items=[{"id": 1}],
        )
        enrichment = RequiredInputsProvider(
            name="enricher",
            provided_fields=[FieldDescriptor("result", "")],
            required_inputs=[
                FieldDescriptor(name="repo_tree", required=True),
            ],
            field_values={
                "result": lambda ctx: f"tree={ctx.current_item.get('repo_tree')}",
            },
        )
        composite = CompositeProvider([
            {"name": "data", "provider": primary, "role": "primary"},
            {
                "name": "enricher",
                "provider": enrichment,
                "item_mapping": {
                    # Explicit mapping overrides auto-wiring
                    "repo_tree": "{{ providers.data.repo_tree }}",
                },
            },
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        # The Jinja2 template renders the list as a string
        result = composite.get_field("result", "", ctx)
        assert "file1" in result

    def test_optional_input_skipped_when_unavailable(self):
        """Optional required_inputs are silently skipped if no upstream provides them."""
        primary = MockProvider(
            name="primary",
            provided_fields=[
                FieldDescriptor("build_system", "dataset"),
            ],
            field_values={"build_system": "gradle"},
            items=[{"id": 1}],
        )
        enrichment = RequiredInputsProvider(
            name="enricher",
            provided_fields=[FieldDescriptor("result", "")],
            required_inputs=[
                FieldDescriptor(name="repo_tree", required=False),
            ],
            field_values={
                "result": lambda ctx: f"has_tree={ctx.current_item.get('repo_tree') is not None}",
            },
        )
        composite = CompositeProvider([
            {"name": "data", "provider": primary, "role": "primary"},
            {
                "name": "enricher",
                "provider": enrichment,
                "item_mapping": {
                    "build_system": "{{ providers.data.build_system }}",
                },
            },
        ])

        ctx = _make_context()
        items = list(composite.iter_items(ctx))
        ctx.current_item = items[0]

        # repo_tree is optional and not available — should not error
        result = composite.get_field("result", "", ctx)
        assert result == "has_tree=False"

    def test_validate_required_inputs_raises_for_unsatisfied(self):
        """prepare() raises when a mandatory required_input cannot be satisfied."""
        primary = MockProvider(
            name="primary",
            provided_fields=[
                FieldDescriptor("build_system", "dataset"),
            ],
            field_values={"build_system": "gradle"},
            items=[{"id": 1}],
        )
        enrichment = RequiredInputsProvider(
            name="enricher",
            provided_fields=[FieldDescriptor("result", "")],
            required_inputs=[
                FieldDescriptor(name="nonexistent_field", required=True),
            ],
        )
        composite = CompositeProvider([
            {"name": "data", "provider": primary, "role": "primary"},
            {"name": "enricher", "provider": enrichment},
        ], validate=False)

        with pytest.raises(CompositeProviderConfigError, match="nonexistent_field"):
            composite.prepare()

    def test_validate_optional_inputs_no_error(self):
        """prepare() does not raise for optional required_inputs that can't be satisfied."""
        primary = MockProvider(
            name="primary",
            provided_fields=[
                FieldDescriptor("build_system", "dataset"),
            ],
            items=[{"id": 1}],
        )
        enrichment = RequiredInputsProvider(
            name="enricher",
            provided_fields=[FieldDescriptor("result", "")],
            required_inputs=[
                FieldDescriptor(name="nonexistent_field", required=False),
            ],
        )
        composite = CompositeProvider([
            {"name": "data", "provider": primary, "role": "primary"},
            {"name": "enricher", "provider": enrichment},
        ], validate=False)

        # Should not raise
        composite.prepare()
