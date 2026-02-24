"""Tests for GradleProvider."""

import json

import pytest

from ee_bench_generator.errors import ProviderError
from ee_bench_generator.metadata import Context, Selection
from ee_bench_gradle.provider import GradleProvider

_GRADLE_TREE = ["build.gradle", "src/main/java/App.java"]
_GRADLE_KTS_TREE = ["build.gradle.kts", "src/main/java/App.java"]
_MAVEN_TREE = ["pom.xml", "src/main/java/App.java"]
_MULTI_MODULE_GRADLE_TREE = [
    "build.gradle",
    "module-a/build.gradle",
    "module-a/src/test/java/com/example/ATest.java",
]

_MULTI_MODULE_TEST_PATCH = (
    "diff --git a/module-a/src/test/java/com/example/ATest.java "
    "b/module-a/src/test/java/com/example/ATest.java\n"
    "--- a/module-a/src/test/java/com/example/ATest.java\n"
    "+++ b/module-a/src/test/java/com/example/ATest.java\n"
)


def _ctx(**item_fields) -> Context:
    return Context(
        selection=Selection(resource="test", filters={}),
        current_item=item_fields,
    )


class TestGradleProviderDetection:
    def test_detects_gradle_from_build_gradle(self):
        prov = GradleProvider()
        prov.prepare()
        ctx = _ctx(repo_tree=_GRADLE_TREE)
        assert prov.get_field("build_system", "", ctx) == "gradle"

    def test_detects_gradle_kotlin_from_kts_only(self):
        prov = GradleProvider()
        prov.prepare()
        ctx = _ctx(repo_tree=_GRADLE_KTS_TREE)
        assert prov.get_field("build_system", "", ctx) == "gradle-kotlin"

    def test_mixed_gradle_and_kts_returns_gradle(self):
        prov = GradleProvider()
        prov.prepare()
        tree = ["build.gradle", "sub/build.gradle.kts"]
        ctx = _ctx(repo_tree=tree)
        assert prov.get_field("build_system", "", ctx) == "gradle"

    def test_is_maven_false_for_gradle(self):
        prov = GradleProvider()
        prov.prepare()
        ctx = _ctx(repo_tree=_GRADLE_TREE)
        assert prov.get_field("is_maven", "", ctx) is False

    def test_returns_none_for_maven_tree(self):
        prov = GradleProvider()
        prov.prepare()
        ctx = _ctx(repo_tree=_MAVEN_TREE)
        assert prov.get_field("build_system", "", ctx) is None
        assert prov.get_field("is_maven", "", ctx) is None
        assert prov.get_field("FAIL_TO_PASS", "", ctx) is None
        assert prov.get_field("PASS_TO_PASS", "", ctx) is None

    def test_returns_none_without_repo_tree(self):
        prov = GradleProvider()
        prov.prepare()
        ctx = _ctx()
        assert prov.get_field("build_system", "", ctx) is None

    def test_returns_none_for_non_list_repo_tree(self):
        prov = GradleProvider()
        prov.prepare()
        ctx = _ctx(repo_tree="not a list")
        assert prov.get_field("build_system", "", ctx) is None

    def test_returns_none_for_empty_tree(self):
        prov = GradleProvider()
        prov.prepare()
        ctx = _ctx(repo_tree=[])
        assert prov.get_field("build_system", "", ctx) is None


class TestGradleProviderTestEnrichment:
    def test_fail_to_pass_enriched(self):
        prov = GradleProvider()
        prov.prepare()
        ctx = _ctx(
            repo_tree=_MULTI_MODULE_GRADLE_TREE,
            test_patch=_MULTI_MODULE_TEST_PATCH,
            FAIL_TO_PASS=json.dumps(["com.example.ATest"]),
        )
        result = json.loads(prov.get_field("FAIL_TO_PASS", "", ctx))
        assert result == ["module-a:com.example.ATest"]

    def test_pass_to_pass_enriched(self):
        prov = GradleProvider()
        prov.prepare()
        ctx = _ctx(
            repo_tree=_MULTI_MODULE_GRADLE_TREE,
            test_patch=_MULTI_MODULE_TEST_PATCH,
            PASS_TO_PASS=json.dumps(["com.example.ATest"]),
        )
        result = json.loads(prov.get_field("PASS_TO_PASS", "", ctx))
        assert result == ["module-a:com.example.ATest"]

    def test_passthrough_without_test_patch(self):
        prov = GradleProvider()
        prov.prepare()
        names = json.dumps(["com.example.ATest"])
        ctx = _ctx(repo_tree=_GRADLE_TREE, FAIL_TO_PASS=names)
        assert prov.get_field("FAIL_TO_PASS", "", ctx) == names

    def test_tree_based_module_detection(self):
        """repo_tree modules used when diff-based extraction yields no results."""
        prov = GradleProvider()
        prov.prepare()
        ctx = _ctx(
            repo_tree=_MULTI_MODULE_GRADLE_TREE,
            test_patch=_MULTI_MODULE_TEST_PATCH,
            FAIL_TO_PASS=json.dumps(["com.example.ATest"]),
        )
        result = json.loads(prov.get_field("FAIL_TO_PASS", "", ctx))
        assert result == ["module-a:com.example.ATest"]


class TestGradleProviderEdgeCases:
    def test_unknown_field_raises(self):
        prov = GradleProvider()
        prov.prepare()
        ctx = _ctx(repo_tree=_GRADLE_TREE)
        with pytest.raises(ProviderError, match="cannot supply"):
            prov.get_field("nonexistent", "", ctx)

    def test_metadata_fields(self):
        prov = GradleProvider()
        meta = prov.metadata
        names = {f.name for f in meta.provided_fields}
        assert names == {"build_system", "is_maven", "FAIL_TO_PASS", "PASS_TO_PASS"}

    def test_metadata_declares_repo_tree_as_required_input(self):
        prov = GradleProvider()
        ri_names = {ri.name for ri in prov.metadata.required_inputs}
        assert "repo_tree" in ri_names
        repo_tree_ri = next(ri for ri in prov.metadata.required_inputs if ri.name == "repo_tree")
        assert repo_tree_ri.required is True
