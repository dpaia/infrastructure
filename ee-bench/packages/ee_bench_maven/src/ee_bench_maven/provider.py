"""MavenProvider — detects Maven projects and enriches test names for multi-module."""

from __future__ import annotations

import re
from typing import Any, Iterator

from ee_bench_generator.build_utils import (
    detect_maven_build_system,
    extract_maven_modules_from_tree,
    extract_module_map,
    prefix_test_names,
)
from ee_bench_generator.errors import ProviderError
from ee_bench_generator.interfaces import Provider
from ee_bench_generator.metadata import Context, FieldDescriptor, ProviderMetadata

_PROVIDED_FIELDS = ["build_system", "is_maven", "FAIL_TO_PASS", "PASS_TO_PASS"]

# Matches test source paths in diffs (module/src/test/java|kotlin/...)
_TEST_SRC_PATTERN = re.compile(
    r"^(?P<module>.+?)/src/test/(?:java|kotlin)/(?P<class_path>.+?)\.(?:java|kt)$"
)


def _enhance_module_map_from_tree(
    test_patch: str, tree_modules: dict[str, str],
) -> dict[str, str]:
    """Build a class_fqn -> module_prefix map using tree-based module info."""
    if not test_patch:
        return {}

    diff_header = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)
    module_map: dict[str, str] = {}

    for match in diff_header.finditer(test_patch):
        path = match.group(2)
        m = _TEST_SRC_PATTERN.match(path)
        if not m:
            continue
        module_dir = m.group("module")
        class_fqn = m.group("class_path").replace("/", ".")
        if module_dir in tree_modules:
            notation = tree_modules[module_dir]
            if notation:
                module_map[class_fqn] = notation
    return module_map


class MavenProvider(Provider):
    """Build-system provider for Maven projects (base/fallback layer).

    Detects whether a project uses Maven by examining ``repo_tree`` for
    ``pom.xml`` files.

    **Required inputs (auto-wired):** ``repo_tree``.

    **Provides:** ``build_system``, ``is_maven``, ``FAIL_TO_PASS``, ``PASS_TO_PASS``.

    Behavior:

    - ``build_system`` → ``"maven"`` when ``pom.xml`` found, else ``""``
    - ``is_maven`` → ``True`` when ``pom.xml`` found, else ``False``
    - ``FAIL_TO_PASS`` / ``PASS_TO_PASS``:
      - For maven multi-module: enrich with module prefix
      - All other cases: passthrough (base/default layer)
    """

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="maven",
            sources=[""],
            provided_fields=[
                FieldDescriptor(name=f, source="") for f in _PROVIDED_FIELDS
            ],
            required_inputs=[
                FieldDescriptor(
                    name="repo_tree",
                    required=True,
                    description="Repository file listing for build-system detection",
                ),
            ],
        )

    def prepare(self, **options: Any) -> None:
        pass

    def get_field(self, name: str, source: str, context: Context) -> Any:
        if name not in _PROVIDED_FIELDS:
            raise ProviderError(
                f"MavenProvider cannot supply field '{name}'"
            )

        item = context.current_item or {}
        repo_tree = item.get("repo_tree")

        is_maven = (
            isinstance(repo_tree, list)
            and detect_maven_build_system(repo_tree)
        )

        if name == "build_system":
            return "maven" if is_maven else ""

        if name == "is_maven":
            return is_maven

        # FAIL_TO_PASS / PASS_TO_PASS
        test_names = item.get(name, "[]")
        test_patch = item.get("test_patch", "")

        module_map: dict[str, str] = {}
        if is_maven and test_patch:
            module_map = extract_module_map(test_patch)

        # Enhance with tree-based detection
        if is_maven and isinstance(repo_tree, list) and not module_map:
            tree_modules = extract_maven_modules_from_tree(repo_tree)
            if tree_modules:
                module_map = _enhance_module_map_from_tree(
                    test_patch, tree_modules
                )

        if module_map:
            return prefix_test_names(str(test_names), module_map)

        return test_names

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:
        raise NotImplementedError("MavenProvider is an enrichment provider")
