"""Tests for build_utils module."""

import json

from ee_bench_generator.build_utils import (
    detect_gradle_build_system,
    detect_maven_build_system,
    extract_gradle_modules_from_tree,
    extract_maven_modules_from_tree,
    extract_module_map,
    prefix_test_names,
)


class TestExtractModuleMap:
    def test_multi_module(self):
        patch = (
            "diff --git a/microservices/product-composite-service/src/test/java/"
            "shop/microservices/composite/product/ProductCompositeApiTests.java "
            "b/microservices/product-composite-service/src/test/java/"
            "shop/microservices/composite/product/ProductCompositeApiTests.java\n"
            "--- a/microservices/product-composite-service/src/test/java/"
            "shop/microservices/composite/product/ProductCompositeApiTests.java\n"
            "+++ b/microservices/product-composite-service/src/test/java/"
            "shop/microservices/composite/product/ProductCompositeApiTests.java\n"
        )
        module_map = extract_module_map(patch)
        assert module_map == {
            "shop.microservices.composite.product.ProductCompositeApiTests":
                "microservices:product-composite-service",
        }

    def test_root_level(self):
        patch = (
            "diff --git a/src/test/java/com/example/AppTest.java "
            "b/src/test/java/com/example/AppTest.java\n"
        )
        module_map = extract_module_map(patch)
        assert module_map == {"com.example.AppTest": ""}

    def test_kotlin(self):
        patch = (
            "diff --git a/module-a/src/test/kotlin/com/example/SomeTest.kt "
            "b/module-a/src/test/kotlin/com/example/SomeTest.kt\n"
        )
        module_map = extract_module_map(patch)
        assert module_map == {"com.example.SomeTest": "module-a"}

    def test_non_test_files_ignored(self):
        patch = (
            "diff --git a/module/src/main/java/com/example/Main.java "
            "b/module/src/main/java/com/example/Main.java\n"
        )
        module_map = extract_module_map(patch)
        assert module_map == {}

    def test_empty_patch(self):
        assert extract_module_map("") == {}

    def test_multiple_modules(self):
        patch = (
            "diff --git a/mod-a/src/test/java/com/a/ATest.java "
            "b/mod-a/src/test/java/com/a/ATest.java\n"
            "diff --git a/mod-b/src/test/java/com/b/BTest.java "
            "b/mod-b/src/test/java/com/b/BTest.java\n"
        )
        module_map = extract_module_map(patch)
        assert module_map == {
            "com.a.ATest": "mod-a",
            "com.b.BTest": "mod-b",
        }

    def test_nested_module_dirs(self):
        patch = (
            "diff --git a/services/api/gateway/src/test/java/com/test/GatewayTest.java "
            "b/services/api/gateway/src/test/java/com/test/GatewayTest.java\n"
        )
        module_map = extract_module_map(patch)
        assert module_map == {"com.test.GatewayTest": "services:api:gateway"}


class TestPrefixTestNames:
    def test_prefixes_matching(self):
        names = json.dumps([
            "com.a.ATest",
            "com.b.BTest",
        ])
        module_map = {
            "com.a.ATest": "mod-a",
            "com.b.BTest": "mod-b",
        }
        result = json.loads(prefix_test_names(names, module_map))
        assert result == ["mod-a:com.a.ATest", "mod-b:com.b.BTest"]

    def test_leaves_unmatched(self):
        names = json.dumps(["com.unknown.Test"])
        module_map = {"com.a.ATest": "mod-a"}
        result = json.loads(prefix_test_names(names, module_map))
        assert result == ["com.unknown.Test"]

    def test_empty_map(self):
        names = json.dumps(["com.a.ATest"])
        result = json.loads(prefix_test_names(names, {}))
        assert result == ["com.a.ATest"]

    def test_empty_input(self):
        result = json.loads(prefix_test_names("[]", {"a": "b"}))
        assert result == []

    def test_empty_prefix_not_prepended(self):
        names = json.dumps(["com.root.Test"])
        module_map = {"com.root.Test": ""}
        result = json.loads(prefix_test_names(names, module_map))
        assert result == ["com.root.Test"]

    def test_invalid_json_passthrough(self):
        assert prefix_test_names("not json", {}) == "not json"

    def test_non_array_json_passthrough(self):
        assert prefix_test_names('"just a string"', {}) == '"just a string"'


class TestExtractGradleModulesFromTree:
    def test_single_root_build_gradle(self):
        tree = ["build.gradle", "src/main/java/App.java"]
        result = extract_gradle_modules_from_tree(tree)
        assert result == {"": ":"}

    def test_multi_module(self):
        tree = [
            "build.gradle",
            "module-a/build.gradle",
            "module-b/build.gradle.kts",
            "module-a/src/main/java/A.java",
        ]
        result = extract_gradle_modules_from_tree(tree)
        assert result[""] == ":"
        assert result["module-a"] == ":module-a"
        assert result["module-b"] == ":module-b"

    def test_nested_modules(self):
        tree = [
            "build.gradle",
            "services/api/build.gradle",
            "services/core/build.gradle.kts",
        ]
        result = extract_gradle_modules_from_tree(tree)
        assert result["services/api"] == ":services:api"
        assert result["services/core"] == ":services:core"

    def test_empty_tree(self):
        assert extract_gradle_modules_from_tree([]) == {}

    def test_no_build_files(self):
        tree = ["src/main/java/App.java", "README.md"]
        assert extract_gradle_modules_from_tree(tree) == {}

    def test_ignores_non_build_files(self):
        tree = ["build.gradle", "build.gradle.bak", "settings.gradle"]
        result = extract_gradle_modules_from_tree(tree)
        assert result == {"": ":"}


class TestExtractMavenModulesFromTree:
    def test_single_root_pom(self):
        tree = ["pom.xml", "src/main/java/App.java"]
        result = extract_maven_modules_from_tree(tree)
        assert result == {"": ""}

    def test_multi_module(self):
        tree = [
            "pom.xml",
            "module-a/pom.xml",
            "module-b/pom.xml",
        ]
        result = extract_maven_modules_from_tree(tree)
        assert result[""] == ""
        assert result["module-a"] == "module-a"
        assert result["module-b"] == "module-b"

    def test_nested_modules(self):
        tree = [
            "pom.xml",
            "services/api/pom.xml",
        ]
        result = extract_maven_modules_from_tree(tree)
        assert result["services/api"] == "services:api"

    def test_empty_tree(self):
        assert extract_maven_modules_from_tree([]) == {}

    def test_no_pom_files(self):
        tree = ["build.gradle", "src/main/java/App.java"]
        assert extract_maven_modules_from_tree(tree) == {}


class TestDetectGradleBuildSystem:
    def test_groovy_only(self):
        assert detect_gradle_build_system(["build.gradle"]) == "gradle"

    def test_kts_only(self):
        assert detect_gradle_build_system(["build.gradle.kts"]) == "gradle-kotlin"

    def test_mixed_returns_gradle(self):
        tree = ["build.gradle", "sub/build.gradle.kts"]
        assert detect_gradle_build_system(tree) == "gradle"

    def test_no_gradle_files(self):
        assert detect_gradle_build_system(["pom.xml", "README.md"]) is None

    def test_empty_tree(self):
        assert detect_gradle_build_system([]) is None

    def test_nested_gradle(self):
        tree = ["services/api/build.gradle.kts"]
        assert detect_gradle_build_system(tree) == "gradle-kotlin"


class TestDetectMavenBuildSystem:
    def test_with_pom(self):
        assert detect_maven_build_system(["pom.xml"]) is True

    def test_without_pom(self):
        assert detect_maven_build_system(["build.gradle"]) is False

    def test_empty_tree(self):
        assert detect_maven_build_system([]) is False

    def test_nested_pom(self):
        assert detect_maven_build_system(["module-a/pom.xml"]) is True
