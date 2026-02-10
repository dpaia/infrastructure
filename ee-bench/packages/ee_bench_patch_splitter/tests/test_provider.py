"""Tests for PatchSplitterProvider."""

from __future__ import annotations

import pytest

from ee_bench_generator.errors import ProviderError
from ee_bench_generator.metadata import Context, Selection
from ee_bench_patch_splitter.provider import (
    PatchSplitterProvider,
    is_test_file,
    split_patch,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SOURCE_DIFF = (
    "diff --git a/src/main/java/com/example/Service.java "
    "b/src/main/java/com/example/Service.java\n"
    "--- a/src/main/java/com/example/Service.java\n"
    "+++ b/src/main/java/com/example/Service.java\n"
    "@@ -10,6 +10,7 @@\n"
    " existing line\n"
    "+new line\n"
)

SAMPLE_TEST_DIFF = (
    "diff --git a/src/test/java/com/example/ServiceTest.java "
    "b/src/test/java/com/example/ServiceTest.java\n"
    "--- a/src/test/java/com/example/ServiceTest.java\n"
    "+++ b/src/test/java/com/example/ServiceTest.java\n"
    "@@ -5,6 +5,7 @@\n"
    " existing test\n"
    "+new test\n"
)

MIXED_PATCH = SAMPLE_SOURCE_DIFF + SAMPLE_TEST_DIFF


def _make_context(patch: str = "") -> Context:
    return Context(
        selection=Selection(resource="pull_requests", filters={}),
        current_item={"patch": patch},
    )


# ---------------------------------------------------------------------------
# is_test_file unit tests
# ---------------------------------------------------------------------------


class TestIsTestFile:
    """Test the is_test_file helper for all supported patterns."""

    @pytest.mark.parametrize(
        "path",
        [
            # JVM / Maven
            "src/test/java/com/example/FooTest.java",
            "src/test/kotlin/com/example/BarTest.kt",
            "module/src/test/resources/data.json",
            # Test directory patterns
            "lib/test/utils.py",
            "lib/tests/test_utils.py",
            # Java naming conventions
            "src/main/java/FooTest.java",
            "src/main/java/FooTests.java",
            "com/example/MyServiceTest.java",
            # Python naming conventions
            "test_module.py",
            "pkg/test_helpers.py",
            "pkg/utils_test.py",  # matched by _test\.
            # JS/TS patterns
            "src/__tests__/App.test.js",
            "src/__test__/helper.ts",
            # Ruby/JS spec patterns
            "spec/models/user_spec.rb",
            "specs/requests/api_spec.rb",
            "app/spec/helper_spec.js",
            "models/UserSpec.java",
        ],
    )
    def test_detects_test_file(self, path: str) -> None:
        assert is_test_file(path), f"Expected '{path}' to be detected as test file"

    @pytest.mark.parametrize(
        "path",
        [
            "src/main/java/com/example/Service.java",
            "src/main/kotlin/com/example/Utils.kt",
            "lib/core/engine.py",
            "src/components/App.tsx",
            "docs/README.md",
            "build.gradle",
            "pom.xml",
        ],
    )
    def test_detects_source_file(self, path: str) -> None:
        assert not is_test_file(path), f"Expected '{path}' to NOT be detected as test file"


# ---------------------------------------------------------------------------
# split_patch unit tests
# ---------------------------------------------------------------------------


class TestSplitPatch:
    def test_empty_patch(self) -> None:
        assert split_patch("") == ("", "")

    def test_whitespace_only_patch(self) -> None:
        assert split_patch("   \n\n  ") == ("", "")

    def test_source_only_patch(self) -> None:
        source, test = split_patch(SAMPLE_SOURCE_DIFF)
        assert source.strip() == SAMPLE_SOURCE_DIFF.strip()
        assert test == ""

    def test_test_only_patch_returns_original_as_source(self) -> None:
        """When all diffs are test files, return the original as source to avoid empty patch."""
        source, test = split_patch(SAMPLE_TEST_DIFF)
        assert source.strip() == SAMPLE_TEST_DIFF.strip()
        assert test == ""

    def test_mixed_patch(self) -> None:
        source, test = split_patch(MIXED_PATCH)
        # Source should contain only the Service.java diff
        assert "Service.java" in source
        assert "ServiceTest.java" not in source
        # Test should contain only the ServiceTest.java diff
        assert "ServiceTest.java" in test
        assert "src/test/java/com/example/ServiceTest.java" in test

    def test_patches_end_with_newline(self) -> None:
        source, test = split_patch(MIXED_PATCH)
        assert source.endswith("\n")
        assert test.endswith("\n")

    def test_multiple_source_files(self) -> None:
        diff_a = (
            "diff --git a/src/main/java/A.java b/src/main/java/A.java\n"
            "--- a/src/main/java/A.java\n"
            "+++ b/src/main/java/A.java\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        diff_b = (
            "diff --git a/src/main/java/B.java b/src/main/java/B.java\n"
            "--- a/src/main/java/B.java\n"
            "+++ b/src/main/java/B.java\n"
            "@@ -1 +1 @@\n"
            "-old b\n"
            "+new b\n"
        )
        combined = diff_a + diff_b
        source, test = split_patch(combined)
        assert "A.java" in source
        assert "B.java" in source
        assert test == ""

    def test_multiple_test_files_with_source(self) -> None:
        test_diff_1 = (
            "diff --git a/src/test/java/T1.java b/src/test/java/T1.java\n"
            "@@ -1 +1 @@\n"
            "+test1\n"
        )
        test_diff_2 = (
            "diff --git a/tests/test_foo.py b/tests/test_foo.py\n"
            "@@ -1 +1 @@\n"
            "+test2\n"
        )
        combined = SAMPLE_SOURCE_DIFF + test_diff_1 + test_diff_2
        source, test = split_patch(combined)
        assert "Service.java" in source
        assert "T1.java" in test
        assert "test_foo.py" in test

    def test_diff_without_file_path_goes_to_source(self) -> None:
        """A malformed diff block (no file path) should be treated as source."""
        weird = "diff --git \nsome content\n"
        source_diff = SAMPLE_SOURCE_DIFF
        combined = source_diff + weird
        source, test = split_patch(combined)
        assert "some content" in source
        assert test == ""


# ---------------------------------------------------------------------------
# PatchSplitterProvider unit tests
# ---------------------------------------------------------------------------


class TestPatchSplitterProvider:
    def setup_method(self) -> None:
        self.provider = PatchSplitterProvider()

    def test_metadata_name(self) -> None:
        assert self.provider.metadata.name == "patch_splitter"

    def test_metadata_sources(self) -> None:
        assert "pull_request" in self.provider.metadata.sources
        assert "issue" in self.provider.metadata.sources

    def test_metadata_provides_patch_and_test_patch(self) -> None:
        meta = self.provider.metadata
        assert meta.can_provide("patch", "pull_request")
        assert meta.can_provide("test_patch", "pull_request")
        assert meta.can_provide("patch", "issue")
        assert meta.can_provide("test_patch", "issue")

    def test_prepare_is_noop(self) -> None:
        # Should not raise
        self.provider.prepare()
        self.provider.prepare(some_option="value")

    def test_iter_items_raises(self) -> None:
        ctx = _make_context()
        with pytest.raises(ProviderError, match="enrichment-only"):
            list(self.provider.iter_items(ctx))

    def test_get_field_patch_source_only(self) -> None:
        ctx = _make_context(SAMPLE_SOURCE_DIFF)
        result = self.provider.get_field("patch", "pull_request", ctx)
        assert "Service.java" in result

    def test_get_field_test_patch_source_only(self) -> None:
        ctx = _make_context(SAMPLE_SOURCE_DIFF)
        result = self.provider.get_field("test_patch", "pull_request", ctx)
        assert result == ""

    def test_get_field_patch_mixed(self) -> None:
        ctx = _make_context(MIXED_PATCH)
        result = self.provider.get_field("patch", "pull_request", ctx)
        assert "Service.java" in result
        assert "ServiceTest.java" not in result

    def test_get_field_test_patch_mixed(self) -> None:
        ctx = _make_context(MIXED_PATCH)
        result = self.provider.get_field("test_patch", "pull_request", ctx)
        assert "ServiceTest.java" in result

    def test_get_field_empty_patch(self) -> None:
        ctx = _make_context("")
        assert self.provider.get_field("patch", "pull_request", ctx) == ""
        assert self.provider.get_field("test_patch", "pull_request", ctx) == ""

    def test_get_field_issue_source(self) -> None:
        ctx = _make_context(MIXED_PATCH)
        result = self.provider.get_field("patch", "issue", ctx)
        assert "Service.java" in result

    def test_get_field_unknown_field_raises(self) -> None:
        ctx = _make_context(MIXED_PATCH)
        with pytest.raises(ProviderError, match="does not provide"):
            self.provider.get_field("unknown_field", "pull_request", ctx)

    def test_get_field_no_current_item(self) -> None:
        ctx = Context(
            selection=Selection(resource="pull_requests", filters={}),
            current_item=None,
        )
        assert self.provider.get_field("patch", "pull_request", ctx) == ""
        assert self.provider.get_field("test_patch", "pull_request", ctx) == ""
