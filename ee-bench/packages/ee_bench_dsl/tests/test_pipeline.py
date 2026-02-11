"""Tests for ee_bench_dsl.pipeline."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

import pytest

from ee_bench_generator.interfaces import Generator, Provider
from ee_bench_generator.metadata import (
    Context,
    FieldDescriptor,
    GeneratorMetadata,
    ProviderMetadata,
    Selection,
)

from ee_bench_dsl.generators import each
from ee_bench_dsl.pipeline import Pipeline
from ee_bench_dsl.providers import from_items


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

DATA = [
    {"id": 1, "name": "alpha"},
    {"id": 2, "name": "beta"},
    {"id": 3, "name": "gamma"},
]


class TestSingleProviderSingleGenerator:
    """Pipeline with from_items + each (no plugin loading)."""

    def test_collect(self):
        results = (
            Pipeline()
            .provider(from_items(DATA))
            .generator(each(lambda item, ctx: {"id": item["id"]}))
            .select("items")
            .collect()
        )
        assert results == [{"id": 1}, {"id": 2}, {"id": 3}]

    def test_iter(self):
        it = (
            Pipeline()
            .provider(from_items(DATA))
            .generator(each(lambda item, ctx: item))
            .select("items")
            .iter()
        )
        first = next(it)
        assert first["id"] == 1

    def test_run_writes_jsonl(self, tmp_path):
        out = tmp_path / "out.jsonl"
        count = (
            Pipeline()
            .provider(from_items(DATA))
            .generator(each(lambda item, ctx: {"id": item["id"]}))
            .select("items")
            .output(str(out))
            .run()
        )
        assert count == 3
        lines = out.read_text().strip().splitlines()
        assert len(lines) == 3
        assert json.loads(lines[0]) == {"id": 1}

    def test_run_writes_json(self, tmp_path):
        out = tmp_path / "out.json"
        count = (
            Pipeline()
            .provider(from_items(DATA))
            .generator(each(lambda item, ctx: {"id": item["id"]}))
            .select("items")
            .output(str(out), fmt="json")
            .run()
        )
        assert count == 3
        parsed = json.loads(out.read_text())
        assert isinstance(parsed, list)
        assert len(parsed) == 3


class TestTransforms:
    def test_transform_modifies_records(self):
        results = (
            Pipeline()
            .provider(from_items(DATA))
            .generator(each(lambda item, ctx: item))
            .select("items")
            .transform(lambda r: {**r, "tag": "x"})
            .collect()
        )
        assert all(r["tag"] == "x" for r in results)

    def test_transform_filters_records(self):
        results = (
            Pipeline()
            .provider(from_items(DATA))
            .generator(each(lambda item, ctx: item))
            .select("items")
            .transform(lambda r: r if r["id"] > 1 else None)
            .collect()
        )
        assert len(results) == 2
        assert results[0]["id"] == 2

    def test_chained_transforms(self):
        results = (
            Pipeline()
            .provider(from_items(DATA))
            .generator(each(lambda item, ctx: item))
            .select("items")
            .transform(lambda r: {**r, "step1": True})
            .transform(lambda r: {**r, "step2": True})
            .collect()
        )
        assert all(r["step1"] and r["step2"] for r in results)


class TestDeferValidation:
    def test_defer_validation_flag(self):
        p = Pipeline().defer_validation()
        assert p._defer_validation is True


class TestErrors:
    def test_no_provider_raises(self):
        with pytest.raises(ValueError, match="no provider"):
            Pipeline().generator(each(lambda i, c: i)).select("x").collect()

    def test_no_generator_raises(self):
        with pytest.raises(ValueError, match="no generator"):
            Pipeline().provider(from_items(DATA)).select("x").collect()

    def test_generator_options_no_generator_raises(self):
        with pytest.raises(ValueError, match="No generator"):
            Pipeline().generator_options(foo="bar")


class TestSelectFilterLimit:
    def test_select_sets_resource(self):
        p = Pipeline().select("my_resource", limit=5, foo="bar")
        assert p._selection_resource == "my_resource"
        assert p._selection_limit == 5
        assert p._selection_filters == {"foo": "bar"}

    def test_filter_merges(self):
        p = Pipeline().select("r").filter(a=1).filter(b=2)
        assert p._selection_filters == {"a": 1, "b": 2}

    def test_limit_sets(self):
        p = Pipeline().limit(10)
        assert p._selection_limit == 10


class TestMultiGenerator:
    """Multiple .generator() calls → MultiGeneratorRunner path."""

    def test_multi_generator_yields_all_records(self):
        results = (
            Pipeline()
            .provider(from_items([{"id": 1}, {"id": 2}]))
            .generator(each(lambda item, ctx: {"gen": "A", "id": item["id"]}))
            .generator(each(lambda item, ctx: {"gen": "B", "id": item["id"]}))
            .defer_validation()
            .select("items")
            .collect()
        )
        # Both generators should produce records
        a_records = [r for r in results if r["gen"] == "A"]
        b_records = [r for r in results if r["gen"] == "B"]
        assert len(a_records) == 2
        assert len(b_records) == 2

    def test_multi_generator_with_per_gen_output(self, tmp_path):
        out_a = tmp_path / "a.jsonl"
        out_b = tmp_path / "b.jsonl"

        results = (
            Pipeline()
            .provider(from_items([{"id": 1}]))
            .generator(
                each(lambda item, ctx: {"gen": "A", "id": item["id"]}),
                output=str(out_a),
            )
            .generator(
                each(lambda item, ctx: {"gen": "B", "id": item["id"]}),
                output=str(out_b),
            )
            .defer_validation()
            .select("items")
            .collect()
        )

        assert out_a.exists()
        assert out_b.exists()
        a_data = [json.loads(l) for l in out_a.read_text().strip().splitlines()]
        b_data = [json.loads(l) for l in out_b.read_text().strip().splitlines()]
        assert a_data == [{"gen": "A", "id": 1}]
        assert b_data == [{"gen": "B", "id": 1}]


class TestMultiProvider:
    """Multiple .provider() calls → CompositeProvider path."""

    def test_composite_provider_is_built(self):
        prov_a = from_items([{"id": 1}], source="dataset_item")
        prov_b = from_items([{"extra": "x"}], source="enrichment")

        # Should not raise — CompositeProvider is constructed
        p = (
            Pipeline()
            .provider(prov_a, role="primary")
            .provider(prov_b)
            .generator(each(lambda item, ctx: item))
            .defer_validation()
            .select("items")
        )
        provider, options = p._build_provider()
        from ee_bench_generator import CompositeProvider

        assert isinstance(provider, CompositeProvider)


class TestGeneratorOptions:
    def test_generator_options_merge(self):
        p = (
            Pipeline()
            .generator(each(lambda i, c: i), output="out.jsonl")
            .generator_options(extra_key="val")
        )
        assert p._generators[-1].options == {"extra_key": "val"}
