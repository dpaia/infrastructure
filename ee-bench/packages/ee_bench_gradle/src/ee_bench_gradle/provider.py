"""GradleProvider — detects Gradle projects and enriches test names with module prefix."""

from __future__ import annotations

import re
from typing import Any, Iterator

from ee_bench_generator.build_utils import (
    detect_gradle_build_system,
    extract_gradle_modules_from_tree,
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
    """Build a class_fqn -> module_prefix map using tree-based module info.

    When ``extract_module_map`` found no modules from the diff itself (e.g.
    single-module repo but build files exist in subdirs), use the tree-based
    module map to match test file paths against known module directories.
    """
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
        # Check if this module_dir is a known tree module
        if module_dir in tree_modules:
            # Use colon-separated notation without leading ':'
            notation = tree_modules[module_dir].lstrip(":")
            module_map[class_fqn] = notation
    return module_map


class GradleProvider(Provider):
    """Build-system provider for Gradle projects.

    Detects whether a project uses Gradle by examining ``repo_tree`` for
    ``build.gradle`` / ``build.gradle.kts`` files.

    **Required inputs (auto-wired):** ``repo_tree``.

    **Provides:** ``build_system``, ``is_maven``, ``FAIL_TO_PASS``, ``PASS_TO_PASS``.

    Behavior:

    - When Gradle build files are detected in ``repo_tree``:
      - ``build_system`` → ``"gradle"`` or ``"gradle-kotlin"``
      - ``is_maven`` → ``False``
      - ``FAIL_TO_PASS`` / ``PASS_TO_PASS`` → enriched with module prefix
    - When no Gradle files found: returns ``None`` for ALL fields →
      chain falls back to MavenProvider
    """

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="gradle",
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
                f"GradleProvider cannot supply field '{name}'"
            )

        item = context.current_item or {}
        repo_tree = item.get("repo_tree")

        if not repo_tree or not isinstance(repo_tree, list):
            return None

        gradle_system = detect_gradle_build_system(repo_tree)
        if gradle_system is None:
            return None

        if name == "build_system":
            return gradle_system

        if name == "is_maven":
            return False

        # FAIL_TO_PASS / PASS_TO_PASS
        test_names = item.get(name, "[]")
        test_patch = item.get("test_patch", "")

        module_map: dict[str, str] = {}
        if test_patch:
            module_map = extract_module_map(test_patch)

        # Enhance with tree-based detection
        if not module_map:
            tree_modules = extract_gradle_modules_from_tree(repo_tree)
            if tree_modules:
                module_map = _enhance_module_map_from_tree(
                    test_patch, tree_modules
                )

        if module_map:
            return prefix_test_names(str(test_names), module_map)

        return test_names

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:
        raise NotImplementedError("GradleProvider is an enrichment provider")
