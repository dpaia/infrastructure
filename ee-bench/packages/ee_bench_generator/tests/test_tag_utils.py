"""Tests for tag_utils.filter_tags."""

from ee_bench_generator.tag_utils import filter_tags


class TestFilterTags:
    def test_exclude_exact_match(self):
        assert filter_tags(["bug", "Epic", "feature"], exclude=["Epic"]) == ["bug", "feature"]

    def test_exclude_glob_pattern(self):
        labels = ["ee-bench-codegen", "bug", "ee-bench-review"]
        assert filter_tags(labels, exclude=["ee-bench-*"]) == ["bug"]

    def test_include_overrides_exclude(self):
        labels = ["bug", "feature", "docs"]
        assert filter_tags(labels, exclude=["*"], include=["bug"]) == ["bug"]

    def test_include_glob_pattern(self):
        labels = ["feature-auth", "feature-ui", "bug"]
        result = filter_tags(labels, exclude=["feature-*"], include=["feature-auth"])
        assert result == ["bug", "feature-auth"]

    def test_no_exclude_no_include(self):
        labels = ["a", "b", "c"]
        assert filter_tags(labels) == ["a", "b", "c"]

    def test_empty_labels(self):
        assert filter_tags([]) == []
        assert filter_tags([], exclude=["*"], include=["bug"]) == []

    def test_exclude_only(self):
        labels = ["bug", "Epic", "Review", "feature"]
        assert filter_tags(labels, exclude=["Epic", "Review"]) == ["bug", "feature"]

    def test_include_only(self):
        """Include without exclude has no effect — all labels already present."""
        labels = ["bug", "feature"]
        assert filter_tags(labels, include=["bug"]) == ["bug", "feature"]

    def test_preserve_order(self):
        labels = ["z", "a", "m", "b"]
        assert filter_tags(labels, exclude=["a"]) == ["z", "m", "b"]

    def test_include_glob_adds_back_multiple(self):
        labels = ["ee-bench-codegen", "ee-bench-review", "bug"]
        result = filter_tags(labels, exclude=["ee-bench-*"], include=["ee-bench-codegen"])
        assert result == ["bug", "ee-bench-codegen"]

    def test_case_sensitive(self):
        """fnmatch is case-sensitive on non-Windows platforms."""
        labels = ["Bug", "bug", "BUG"]
        assert filter_tags(labels, exclude=["bug"]) == ["Bug", "BUG"]
