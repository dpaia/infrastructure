"""Tests for ee_bench_dsl.providers."""

from __future__ import annotations

import pytest

from ee_bench_generator.metadata import Context, Selection

from ee_bench_dsl.providers import FunctionProvider, from_items


def _make_context() -> Context:
    return Context(selection=Selection(resource="items", filters={}))


class TestFunctionProvider:
    def test_iter_items_from_list(self):
        prov = FunctionProvider([{"a": 1}, {"a": 2}])
        prov.prepare()
        ctx = _make_context()
        items = list(prov.iter_items(ctx))
        assert items == [{"a": 1}, {"a": 2}]

    def test_iter_items_from_callable(self):
        prov = FunctionProvider(lambda: [{"x": 10}])
        prov.prepare()
        ctx = _make_context()
        items = list(prov.iter_items(ctx))
        assert items == [{"x": 10}]

    def test_metadata_discovers_fields(self):
        prov = FunctionProvider([{"id": 1, "name": "a"}], source="record")
        meta = prov.metadata
        assert meta.name == "function_provider"
        assert meta.sources == ["record"]
        field_names = {f.name for f in meta.provided_fields}
        assert field_names == {"id", "name"}

    def test_metadata_empty_data(self):
        prov = FunctionProvider([])
        meta = prov.metadata
        assert meta.provided_fields == []

    def test_get_field_returns_from_current_item(self):
        prov = FunctionProvider([{"id": 1}])
        prov.prepare()
        ctx = _make_context()
        ctx.current_item = {"id": 42}
        assert prov.get_field("id", "item", ctx) == 42

    def test_get_field_missing_returns_none(self):
        prov = FunctionProvider([{"id": 1}])
        prov.prepare()
        ctx = _make_context()
        ctx.current_item = {"id": 1}
        assert prov.get_field("missing", "item", ctx) is None


class TestFromItems:
    def test_creates_function_provider(self):
        prov = from_items([{"k": "v"}])
        assert isinstance(prov, FunctionProvider)

    def test_custom_source(self):
        prov = from_items([{"k": "v"}], source="dataset_item")
        assert prov.metadata.sources == ["dataset_item"]
