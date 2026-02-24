"""Tests for MavenProvider."""

import json

import pytest

from ee_bench_generator.errors import ProviderError
from ee_bench_generator.metadata import Context, Selection
from ee_bench_maven.provider import MavenProvider

_MAVEN_TREE = ["pom.xml", "src/main/java/App.java"]
_GRADLE_TREE = ["build.gradle", "src/main/java/App.java"]
_MULTI_MODULE_MAVEN_TREE = [
    "pom.xml",
    "module-a/pom.xml",
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


class TestMavenProviderDetection:
    def test_detects_maven_from_pom_xml(self):
        prov = MavenProvider()
        prov.prepare()
        ctx = _ctx(repo_tree=_MAVEN_TREE)
        assert prov.get_field("build_system", "", ctx) == "maven"

    def test_is_maven_true(self):
        prov = MavenProvider()
        prov.prepare()
        ctx = _ctx(repo_tree=_MAVEN_TREE)
        assert prov.get_field("is_maven", "", ctx) is True

    def test_not_maven_for_gradle_tree(self):
        prov = MavenProvider()
        prov.prepare()
        ctx = _ctx(repo_tree=_GRADLE_TREE)
        assert prov.get_field("build_system", "", ctx) == ""
        assert prov.get_field("is_maven", "", ctx) is False

    def test_not_maven_without_repo_tree(self):
        prov = MavenProvider()
        prov.prepare()
        ctx = _ctx()
        assert prov.get_field("build_system", "", ctx) == ""
        assert prov.get_field("is_maven", "", ctx) is False

    def test_not_maven_for_empty_tree(self):
        prov = MavenProvider()
        prov.prepare()
        ctx = _ctx(repo_tree=[])
        assert prov.get_field("build_system", "", ctx) == ""
        assert prov.get_field("is_maven", "", ctx) is False


class TestMavenProviderTestEnrichment:
    def test_fail_to_pass_enriched_for_maven_multi_module(self):
        prov = MavenProvider()
        prov.prepare()
        ctx = _ctx(
            repo_tree=_MULTI_MODULE_MAVEN_TREE,
            test_patch=_MULTI_MODULE_TEST_PATCH,
            FAIL_TO_PASS=json.dumps(["com.example.ATest"]),
        )
        result = json.loads(prov.get_field("FAIL_TO_PASS", "", ctx))
        assert result == ["module-a:com.example.ATest"]

    def test_pass_to_pass_enriched_for_maven_multi_module(self):
        prov = MavenProvider()
        prov.prepare()
        ctx = _ctx(
            repo_tree=_MULTI_MODULE_MAVEN_TREE,
            test_patch=_MULTI_MODULE_TEST_PATCH,
            PASS_TO_PASS=json.dumps(["com.example.ATest"]),
        )
        result = json.loads(prov.get_field("PASS_TO_PASS", "", ctx))
        assert result == ["module-a:com.example.ATest"]

    def test_passthrough_for_non_maven(self):
        prov = MavenProvider()
        prov.prepare()
        names = json.dumps(["com.example.ATest"])
        ctx = _ctx(
            repo_tree=_GRADLE_TREE,
            test_patch=_MULTI_MODULE_TEST_PATCH,
            FAIL_TO_PASS=names,
        )
        assert prov.get_field("FAIL_TO_PASS", "", ctx) == names

    def test_passthrough_without_test_patch(self):
        prov = MavenProvider()
        prov.prepare()
        names = json.dumps(["com.example.ATest"])
        ctx = _ctx(repo_tree=_MAVEN_TREE, FAIL_TO_PASS=names)
        assert prov.get_field("FAIL_TO_PASS", "", ctx) == names


class TestMavenProviderEdgeCases:
    def test_unknown_field_raises(self):
        prov = MavenProvider()
        prov.prepare()
        ctx = _ctx(repo_tree=_MAVEN_TREE)
        with pytest.raises(ProviderError, match="cannot supply"):
            prov.get_field("nonexistent", "", ctx)

    def test_metadata_fields(self):
        prov = MavenProvider()
        meta = prov.metadata
        names = {f.name for f in meta.provided_fields}
        assert names == {"build_system", "is_maven", "FAIL_TO_PASS", "PASS_TO_PASS"}

    def test_metadata_declares_repo_tree_as_required_input(self):
        prov = MavenProvider()
        ri_names = {ri.name for ri in prov.metadata.required_inputs}
        assert "repo_tree" in ri_names
        repo_tree_ri = next(ri for ri in prov.metadata.required_inputs if ri.name == "repo_tree")
        assert repo_tree_ri.required is True
