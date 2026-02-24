"""Shared utilities for build-system providers (Gradle / Maven)."""

from __future__ import annotations

import json
import re

# Matches diff headers: diff --git a/<path> b/<path>
_DIFF_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)

# Matches test source paths (Java/Kotlin convention)
_TEST_SRC_PATTERN = re.compile(
    r"^(?P<module>.+?)/src/test/(?:java|kotlin)/(?P<class_path>.+?)\.(?:java|kt)$"
)

# Root-level test source (no module prefix)
_ROOT_TEST_SRC_PATTERN = re.compile(
    r"^src/test/(?:java|kotlin)/(?P<class_path>.+?)\.(?:java|kt)$"
)


def extract_module_map(test_patch: str) -> dict[str, str]:
    """Extract a mapping of test class FQN -> module prefix from a unified diff.

    For each ``diff --git`` header whose path contains ``/src/test/``:

    - **Module dir** = everything before ``/src/test/``
      (e.g. ``microservices/product-composite-service``)
    - **Module prefix** = module dir with ``/`` replaced by ``:``
      (e.g. ``microservices:product-composite-service``)
    - **Class FQN** = path after ``/src/test/java/`` (or ``kotlin/``),
      ``/`` → ``.``, extension stripped
      (e.g. ``shop.microservices.composite.product.ProductCompositeApiTests``)

    Root-level tests (``src/test/java/...`` with no module prefix dir)
    get an empty module prefix.

    Returns:
        Dict mapping ``class_fqn -> module_prefix``.
    """
    module_map: dict[str, str] = {}

    for match in _DIFF_HEADER.finditer(test_patch):
        path = match.group(2)  # b/ path

        # Try module-level path first
        m = _TEST_SRC_PATTERN.match(path)
        if m:
            module_dir = m.group("module")
            module_prefix = module_dir.replace("/", ":")
            class_fqn = m.group("class_path").replace("/", ".")
            module_map[class_fqn] = module_prefix
            continue

        # Try root-level path
        m = _ROOT_TEST_SRC_PATTERN.match(path)
        if m:
            class_fqn = m.group("class_path").replace("/", ".")
            module_map[class_fqn] = ""

    return module_map


def extract_gradle_modules_from_tree(repo_tree: list[str]) -> dict[str, str]:
    """Extract Gradle module map from a repository file listing.

    Scans *repo_tree* for ``build.gradle`` and ``build.gradle.kts`` files.
    Each directory containing one is treated as a Gradle module.

    Returns:
        Dict mapping ``dir_path -> gradle_module_notation``
        where notation uses ``:`` separators (e.g. ``"services/api" -> ":services:api"``).
        Root-level build files map to ``":"``.
    """
    module_map: dict[str, str] = {}
    for path in repo_tree:
        filename = path.rsplit("/", 1)[-1] if "/" in path else path
        if filename in ("build.gradle", "build.gradle.kts"):
            dir_path = path.rsplit("/", 1)[0] if "/" in path else ""
            if dir_path:
                notation = ":" + dir_path.replace("/", ":")
            else:
                notation = ":"
            module_map[dir_path] = notation
    return module_map


def extract_maven_modules_from_tree(repo_tree: list[str]) -> dict[str, str]:
    """Extract Maven module map from a repository file listing.

    Scans *repo_tree* for ``pom.xml`` files.  Each directory containing
    one is treated as a Maven module.

    Returns:
        Dict mapping ``dir_path -> module_notation``
        where notation uses ``:`` separators (e.g. ``"services/api" -> "services:api"``).
        Root-level ``pom.xml`` maps to ``""``.
    """
    module_map: dict[str, str] = {}
    for path in repo_tree:
        filename = path.rsplit("/", 1)[-1] if "/" in path else path
        if filename == "pom.xml":
            dir_path = path.rsplit("/", 1)[0] if "/" in path else ""
            notation = dir_path.replace("/", ":") if dir_path else ""
            module_map[dir_path] = notation
    return module_map


def detect_gradle_build_system(repo_tree: list[str]) -> str | None:
    """Detect Gradle build system variant from a repository file listing.

    Returns:
        ``"gradle-kotlin"`` if only ``.kts`` build files are found,
        ``"gradle"`` if any ``build.gradle`` (Groovy) file is found,
        or ``None`` if no Gradle build files exist.
    """
    has_groovy = False
    has_kts = False
    for path in repo_tree:
        filename = path.rsplit("/", 1)[-1] if "/" in path else path
        if filename == "build.gradle":
            has_groovy = True
        elif filename == "build.gradle.kts":
            has_kts = True
    if has_kts and not has_groovy:
        return "gradle-kotlin"
    if has_groovy or has_kts:
        return "gradle"
    return None


def detect_maven_build_system(repo_tree: list[str]) -> bool:
    """Return ``True`` if any ``pom.xml`` is found in *repo_tree*."""
    return any(
        (path.rsplit("/", 1)[-1] if "/" in path else path) == "pom.xml"
        for path in repo_tree
    )


def prefix_test_names(test_names_json: str, module_map: dict[str, str]) -> str:
    """Prefix test class names with their module path.

    Parses *test_names_json* as a JSON array of test class names,
    prefixes each with ``module_prefix:`` when the class is found in
    *module_map* **and** the prefix is non-empty. Unmatched names and
    names with empty prefix are left unchanged.

    Returns:
        A JSON array string with prefixed test names.
    """
    try:
        names: list[str] = json.loads(test_names_json)
    except (json.JSONDecodeError, TypeError):
        return test_names_json

    if not isinstance(names, list):
        return test_names_json

    result: list[str] = []
    for name in names:
        prefix = module_map.get(name, "")
        if prefix:
            result.append(f"{prefix}:{name}")
        else:
            result.append(name)

    return json.dumps(result)
