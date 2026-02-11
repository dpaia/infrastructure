"""Tests for ee_bench_dsl.generators."""

from __future__ import annotations

import pytest

from ee_bench_generator.metadata import Context, Selection

from ee_bench_dsl.generators import FunctionGenerator, each
from ee_bench_dsl.providers import FunctionProvider


def _make_context() -> Context:
    return Context(selection=Selection(resource="items", filters={}))


class TestFunctionGenerator:
    def test_item_fn_generates_records(self):
        gen = FunctionGenerator(item_fn=lambda item, ctx: {"doubled": item["n"] * 2})
        prov = FunctionProvider([{"n": 1}, {"n": 2}, {"n": 3}])
        prov.prepare()
        ctx = _make_context()

        results = list(gen.generate(prov, ctx))
        assert results == [{"doubled": 2}, {"doubled": 4}, {"doubled": 6}]

    def test_item_fn_can_skip_with_none(self):
        gen = FunctionGenerator(
            item_fn=lambda item, ctx: item if item["n"] > 1 else None
        )
        prov = FunctionProvider([{"n": 1}, {"n": 2}, {"n": 3}])
        prov.prepare()
        ctx = _make_context()

        results = list(gen.generate(prov, ctx))
        assert results == [{"n": 2}, {"n": 3}]

    def test_process_fn_generates_records(self):
        def bulk(provider, ctx):
            for item in provider.iter_items(ctx):
                yield {"id": item["id"]}

        gen = FunctionGenerator(process_fn=bulk)
        prov = FunctionProvider([{"id": "a"}, {"id": "b"}])
        prov.prepare()
        ctx = _make_context()

        results = list(gen.generate(prov, ctx))
        assert results == [{"id": "a"}, {"id": "b"}]

    def test_both_fns_raises(self):
        with pytest.raises(ValueError, match="not both"):
            FunctionGenerator(
                item_fn=lambda i, c: i,
                process_fn=lambda p, c: iter([]),
            )

    def test_neither_fn_raises(self):
        with pytest.raises(ValueError, match="either"):
            FunctionGenerator()

    def test_metadata(self):
        gen = FunctionGenerator(item_fn=lambda i, c: i)
        meta = gen.metadata
        assert meta.name == "function_generator"
        assert meta.required_fields == []

    def test_output_schema(self):
        gen = FunctionGenerator(item_fn=lambda i, c: i)
        assert gen.output_schema() == {"type": "object"}


class TestEach:
    def test_creates_function_generator(self):
        gen = each(lambda item, ctx: {"id": item["id"]})
        assert isinstance(gen, FunctionGenerator)

    def test_each_generates_records(self):
        gen = each(lambda item, ctx: {"val": item["x"] + 1})
        prov = FunctionProvider([{"x": 10}, {"x": 20}])
        prov.prepare()
        ctx = _make_context()

        results = list(gen.generate(prov, ctx))
        assert results == [{"val": 11}, {"val": 21}]
