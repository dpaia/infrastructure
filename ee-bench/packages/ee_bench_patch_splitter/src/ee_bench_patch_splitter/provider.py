"""PatchSplitterProvider - splits unified diffs into source and test patches."""

from __future__ import annotations

import re
from typing import Any, Iterator

from ee_bench_generator import Provider
from ee_bench_generator.errors import ProviderError
from ee_bench_generator.metadata import Context, FieldDescriptor, ProviderMetadata

# Patterns that identify test files across common languages/frameworks
_TEST_PATTERNS = [
    r"/test/",
    r"/tests/",
    r"_test\.",
    r"Test\.",
    r"Tests\.",
    r"/src/test/",
    r"/main/test/",
    r"/spec/",
    r"/specs/",
    r"_spec\.",
    r"Spec\.",
    r"__tests__",
    r"__test__",
    r"_test_",
    r"test_",
]


def is_test_file(file_path: str) -> bool:
    """Determine whether *file_path* belongs to a test directory or follows a test-file naming convention."""
    return any(re.search(p, file_path, re.IGNORECASE) for p in _TEST_PATTERNS)


def split_patch(patch: str) -> tuple[str, str]:
    """Split a unified diff into ``(source_patch, test_patch)``.

    Each ``diff --git`` block is classified by its file path using
    :func:`is_test_file`.  If *every* block is a test file the full
    patch is returned as ``source_patch`` so that downstream consumers
    always have a non-empty patch to apply.

    Returns:
        A ``(source_patch, test_patch)`` tuple.
    """
    if not patch or not patch.strip():
        return ("", "")

    # Split into individual file diffs while preserving the "diff --git" prefix
    parts = re.split(r"(diff --git )", patch)

    file_diffs: list[str] = []
    for i in range(1, len(parts), 2):
        if i + 1 < len(parts):
            file_diffs.append(parts[i] + parts[i + 1])

    if not file_diffs:
        return (patch, "")

    source_diffs: list[str] = []
    test_diffs: list[str] = []

    for diff in file_diffs:
        match = re.search(r"diff --git a/(.*?) b/", diff)
        if not match:
            source_diffs.append(diff)
            continue

        file_path = match.group(1)
        if is_test_file(file_path):
            test_diffs.append(diff)
        else:
            source_diffs.append(diff)

    # If all diffs are test files, return the original patch as source
    # to ensure patch is never empty
    if not source_diffs and test_diffs:
        return (patch, "")

    source_patch = "\n".join(source_diffs).strip()
    test_patch = "\n".join(test_diffs).strip()

    # Ensure patches end with newline when non-empty
    if source_patch and not source_patch.endswith("\n"):
        source_patch += "\n"
    if test_patch and not test_patch.endswith("\n"):
        test_patch += "\n"

    return (source_patch, test_patch)


class PatchSplitterProvider(Provider):
    """Enrichment-only provider that splits a full patch into source and test parts.

    This provider is designed to be used as an enrichment provider in a
    multi-provider composite configuration.  It reads the ``patch`` field
    from the current item (resolved via ``item_mapping``) and returns the
    source-only or test-only portion depending on which field is requested.

    **Not a primary provider** -- calling :meth:`iter_items` will raise
    :class:`~ee_bench_generator.errors.ProviderError`.
    """

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="patch_splitter",
            sources=["pull_request", "issue"],
            provided_fields=[
                FieldDescriptor(
                    "patch",
                    source="pull_request",
                    description="Source-only diff (test files removed)",
                ),
                FieldDescriptor(
                    "test_patch",
                    source="pull_request",
                    description="Test-only diff",
                ),
                FieldDescriptor(
                    "patch",
                    source="issue",
                    description="Source-only diff (test files removed)",
                ),
                FieldDescriptor(
                    "test_patch",
                    source="issue",
                    description="Test-only diff",
                ),
            ],
        )

    def prepare(self, **options: Any) -> None:  # noqa: ARG002
        """No-op -- this is a pure-transform provider."""

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:  # noqa: ARG002
        raise ProviderError(
            "PatchSplitterProvider is an enrichment-only provider and cannot "
            "be used as a primary provider. Use it with item_mapping in a "
            "multi-provider configuration."
        )

    def get_field(self, name: str, source: str, context: Context) -> Any:
        if name not in ("patch", "test_patch"):
            raise ProviderError(
                f"PatchSplitterProvider does not provide field '{name}'"
            )

        current = context.current_item or {}
        full_patch = current.get("patch", "")

        source_patch, test_patch = split_patch(full_patch)

        if name == "patch":
            return source_patch
        return test_patch
