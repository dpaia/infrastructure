"""Tests for HuggingFaceDatasetProvider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ee_bench_generator.metadata import Context, Selection

from ee_bench_huggingface.provider import (
    HuggingFaceDatasetProvider,
    _compile_filters,
    _row_matches,
)


@pytest.fixture
def provider():
    return HuggingFaceDatasetProvider()


@pytest.fixture
def mock_dataset():
    """Create a mock HuggingFace dataset."""
    dataset = MagicMock()
    dataset.column_names = [
        "instance_id", "repo", "base_commit", "patch", "test_patch",
        "problem_statement", "hints_text", "version", "repo_language",
        "FAIL_TO_PASS", "PASS_TO_PASS",
    ]
    dataset.__len__ = MagicMock(return_value=3)

    rows = [
        {
            "instance_id": "django__django-16255",
            "repo": "django/django",
            "base_commit": "abc123",
            "patch": "diff --git a/test.py b/test.py",
            "test_patch": "",
            "problem_statement": "Fix sitemap issue",
            "hints_text": "Check the sitemap module",
            "version": "4.2",
            "repo_language": "Python",
            "FAIL_TO_PASS": '["test_one"]',
            "PASS_TO_PASS": '["test_two"]',
        },
        {
            "instance_id": "flask__flask-5001",
            "repo": "pallets/flask",
            "base_commit": "def456",
            "patch": "diff --git a/app.py b/app.py",
            "test_patch": "",
            "problem_statement": "Fix routing",
            "hints_text": "",
            "version": "2.3",
            "repo_language": "Python",
            "FAIL_TO_PASS": '["test_route"]',
            "PASS_TO_PASS": '[]',
        },
        {
            "instance_id": "express__express-100",
            "repo": "expressjs/express",
            "base_commit": "ghi789",
            "patch": "diff --git a/index.js b/index.js",
            "test_patch": "",
            "problem_statement": "Fix middleware",
            "hints_text": "",
            "version": "4.18",
            "repo_language": "JavaScript",
            "FAIL_TO_PASS": '["test_mw"]',
            "PASS_TO_PASS": '[]',
        },
    ]

    def getitem(self_or_idx, idx=None):
        # Handle both MagicMock method call (self, idx) and direct call (idx)
        if idx is None:
            idx = self_or_idx
        return rows[idx]

    dataset.__getitem__ = getitem
    return dataset


class TestMetadata:
    def test_initial_metadata(self, provider):
        meta = provider.metadata
        assert meta.name == "huggingface_dataset"
        assert "dataset_item" in meta.sources
        assert "dataset_metadata" in meta.sources
        # Should always have checksum field
        assert any(
            f.name == "checksum" and f.source == "dataset_metadata"
            for f in meta.provided_fields
        )

    def test_metadata_after_prepare(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(dataset_name="test/dataset")
        meta = provider.metadata
        # Should have all dataset columns as fields
        assert any(f.name == "instance_id" for f in meta.provided_fields)
        assert any(f.name == "repo_language" for f in meta.provided_fields)


class TestPrepare:
    def test_prepare_requires_dataset_name_or_path(self, provider):
        with pytest.raises(Exception, match="Either 'dataset_name' or 'dataset_path'"):
            provider.prepare()

    def test_prepare_with_dataset_name(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(dataset_name="ScaleAI/SWE-bench_Pro", split="test")

        assert provider._dataset is not None
        assert "instance_id" in provider._column_names

    def test_prepare_empty_hf_token_treated_as_none(self, provider, mock_dataset):
        """Empty string token (from ${HF_TOKEN:-}) should be treated as None."""
        with patch("datasets.load_dataset", return_value=mock_dataset) as mock_load:
            provider.prepare(dataset_name="test/dataset", hf_token="  ")

        # Should not pass token to load_dataset
        call_kwargs = mock_load.call_args
        assert "token" not in call_kwargs.kwargs


class TestGetField:
    def test_get_field_not_prepared(self, provider):
        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        with pytest.raises(Exception, match="not prepared"):
            provider.get_field("instance_id", "dataset_item", ctx)

    def test_get_dataset_item_field(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(dataset_name="test/dataset")

        item = {
            "instance_id": "django__django-16255",
            "repo": "django/django",
            "repo_language": "Python",
        }
        ctx = Context(
            selection=Selection(resource="dataset_items", filters={}),
            current_item=item,
        )

        assert provider.get_field("instance_id", "dataset_item", ctx) == "django__django-16255"
        assert provider.get_field("repo_language", "dataset_item", ctx) == "Python"

    def test_get_checksum_field(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(dataset_name="test/dataset")

        item = {"instance_id": "test", "repo": "org/repo"}
        ctx = Context(
            selection=Selection(resource="dataset_items", filters={}),
            current_item=item,
        )

        checksum = provider.get_field("checksum", "dataset_metadata", ctx)
        assert isinstance(checksum, str)
        assert len(checksum) == 64  # SHA-256 hex

    def test_get_field_missing_column(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(dataset_name="test/dataset")

        item = {"instance_id": "test"}
        ctx = Context(
            selection=Selection(resource="dataset_items", filters={}),
            current_item=item,
        )

        with pytest.raises(Exception, match="not found"):
            provider.get_field("nonexistent", "dataset_item", ctx)


class TestIterItems:
    def test_iter_all_items(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(dataset_name="test/dataset")

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 3

    def test_iter_with_limit(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(dataset_name="test/dataset")

        ctx = Context(selection=Selection(resource="dataset_items", filters={}, limit=2))
        items = list(provider.iter_items(ctx))
        assert len(items) == 2

    # --- Legacy filter options (backward compatibility) ---

    def test_iter_with_language_filter(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(dataset_name="test/dataset", filter_language="Python")

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 2  # Only Python items
        assert all(item["repo_language"] == "Python" for item in items)

    def test_iter_with_repo_filter(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(
                dataset_name="test/dataset",
                filter_repos=["django/django"],
            )

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 1
        assert items[0]["repo"] == "django/django"

    def test_iter_with_exclude_repos(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(
                dataset_name="test/dataset",
                exclude_repos=["django/django"],
            )

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 2
        assert all(item["repo"] != "django/django" for item in items)

    # --- Generic filters option ---

    def test_iter_with_generic_eq_shorthand(self, provider, mock_dataset):
        """Scalar value in filters dict is shorthand for eq."""
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(
                dataset_name="test/dataset",
                filters={"repo_language": "JavaScript"},
            )

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 1
        assert items[0]["instance_id"] == "express__express-100"

    def test_iter_with_generic_in(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(
                dataset_name="test/dataset",
                filters={"repo": {"in": ["django/django", "pallets/flask"]}},
            )

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 2
        repos = {item["repo"] for item in items}
        assert repos == {"django/django", "pallets/flask"}

    def test_iter_with_generic_not_in(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(
                dataset_name="test/dataset",
                filters={"repo": {"not_in": ["expressjs/express"]}},
            )

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 2
        assert all(item["repo"] != "expressjs/express" for item in items)

    def test_iter_with_generic_contains(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(
                dataset_name="test/dataset",
                filters={"instance_id": {"contains": "django"}},
            )

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 1
        assert items[0]["instance_id"] == "django__django-16255"

    def test_iter_with_generic_not_contains(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(
                dataset_name="test/dataset",
                filters={"instance_id": {"not_contains": "django"}},
            )

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 2

    def test_iter_with_generic_regex(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(
                dataset_name="test/dataset",
                filters={"version": {"regex": r"^4\."}},
            )

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 2  # version "4.2" and "4.18"

    def test_iter_with_generic_startswith(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(
                dataset_name="test/dataset",
                filters={"instance_id": {"startswith": "flask"}},
            )

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 1
        assert items[0]["instance_id"] == "flask__flask-5001"

    def test_iter_with_generic_endswith(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(
                dataset_name="test/dataset",
                filters={"instance_id": {"endswith": "100"}},
            )

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 1
        assert items[0]["instance_id"] == "express__express-100"

    def test_iter_with_generic_not_eq(self, provider, mock_dataset):
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(
                dataset_name="test/dataset",
                filters={"repo_language": {"not_eq": "Python"}},
            )

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 1
        assert items[0]["repo_language"] == "JavaScript"

    def test_iter_with_multiple_filters(self, provider, mock_dataset):
        """Multiple filter fields are ANDed together."""
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(
                dataset_name="test/dataset",
                filters={
                    "repo_language": "Python",
                    "instance_id": {"contains": "flask"},
                },
            )

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 1
        assert items[0]["instance_id"] == "flask__flask-5001"

    def test_iter_with_multiple_ops_on_same_field(self, provider, mock_dataset):
        """Multiple operators on the same field are all applied (ANDed)."""
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(
                dataset_name="test/dataset",
                filters={
                    "instance_id": {"contains": "__", "not_contains": "express"},
                },
            )

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 2
        ids = {item["instance_id"] for item in items}
        assert ids == {"django__django-16255", "flask__flask-5001"}

    def test_generic_filters_override_legacy(self, provider, mock_dataset):
        """When both generic filters and legacy options are given, they merge."""
        with patch("datasets.load_dataset", return_value=mock_dataset):
            provider.prepare(
                dataset_name="test/dataset",
                filter_language="Python",
                filters={"instance_id": {"contains": "flask"}},
            )

        ctx = Context(selection=Selection(resource="dataset_items", filters={}))
        items = list(provider.iter_items(ctx))
        assert len(items) == 1
        assert items[0]["instance_id"] == "flask__flask-5001"


class TestChecksum:
    def test_checksum_deterministic(self):
        row = {"a": 1, "b": "hello"}
        c1 = HuggingFaceDatasetProvider._compute_checksum(row)
        c2 = HuggingFaceDatasetProvider._compute_checksum(row)
        assert c1 == c2

    def test_checksum_different_for_different_data(self):
        row1 = {"a": 1}
        row2 = {"a": 2}
        c1 = HuggingFaceDatasetProvider._compute_checksum(row1)
        c2 = HuggingFaceDatasetProvider._compute_checksum(row2)
        assert c1 != c2


class TestCompileFilters:
    def test_empty_dict(self):
        assert _compile_filters({}) == []

    def test_shorthand_scalar(self):
        result = _compile_filters({"repo_language": "Python"})
        assert result == [("repo_language", "eq", "Python")]

    def test_advanced_single_op(self):
        result = _compile_filters({"repo": {"in": ["a", "b"]}})
        assert result == [("repo", "in", ["a", "b"])]

    def test_advanced_multiple_ops(self):
        result = _compile_filters({"x": {"contains": "foo", "not_contains": "bar"}})
        assert len(result) == 2
        ops = {op for _, op, _ in result}
        assert ops == {"contains", "not_contains"}

    def test_unknown_operator_raises(self):
        with pytest.raises(Exception, match="Unknown filter operator 'gt'"):
            _compile_filters({"x": {"gt": 5}})


class TestRowMatches:
    def test_empty_filters_matches_all(self):
        assert _row_matches({"a": 1}, [])

    def test_eq_match(self):
        compiled = [("lang", "eq", "Python")]
        assert _row_matches({"lang": "Python"}, compiled)
        assert not _row_matches({"lang": "Java"}, compiled)

    def test_missing_field_uses_empty_string(self):
        compiled = [("missing", "eq", "")]
        assert _row_matches({"other": "x"}, compiled)

    def test_all_conditions_must_match(self):
        compiled = [("a", "eq", "1"), ("b", "eq", "2")]
        assert _row_matches({"a": "1", "b": "2"}, compiled)
        assert not _row_matches({"a": "1", "b": "3"}, compiled)
