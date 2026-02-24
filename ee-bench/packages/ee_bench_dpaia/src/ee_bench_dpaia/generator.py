"""DPAIA Generator implementations.

.. deprecated::
    ``DpaiaJvmGenerator`` and ``DpaiaSweProGenerator`` are deprecated.
    Use :class:`~ee_bench_dpaia.unified_generator.EEBenchCodegenGenerator` instead.
"""

from __future__ import annotations

import json
import warnings
from typing import Any, Iterator

from ee_bench_generator import Generator, Provider
from ee_bench_generator.clock import now_iso8601_utc
from ee_bench_generator.metadata import Context, FieldDescriptor, GeneratorMetadata


# All SWE-bench Pro metadata field names (excluding instance_id which is handled separately)
_SWE_PRO_METADATA_FIELDS = [
    "repo",
    "base_commit",
    "version",
    "repo_language",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "environment_setup_commit",
    "requirements",
    "interface",
    "issue_specificity",
    "issue_categories",
    "dockerhub_tag",
    "before_repo_set_cmd",
    "selected_test_files_to_run",
    "created_at",
    "checksum",
    "dataset",
    "run_script_name",
    "parser_name",
]


class DpaiaJvmGenerator(Generator):
    """Generator that produces DPAIA-format dataset records for JVM projects.

    This generator creates records compatible with the SWE-bench evaluation
    framework, specifically designed for Java/JVM codebases.

    Fields are declared without sources so they match any provider that
    supplies a field with the same name (pull_request, issue, repository, etc.).

    Output schema includes:
    - instance_id: Unique identifier (owner__repo__number)
    - repo: Repository clone URL
    - base_commit: Commit SHA to checkout before applying patch
    - patch: The diff that fixes the issue
    - problem_statement: Issue/PR description
    - hints_text: Optional hints for solving the problem
    - FAIL_TO_PASS: JSON array of tests that should fail then pass
    - PASS_TO_PASS: JSON array of tests that should always pass
    - created_at: ISO8601 timestamp when record was generated
    - issue_numbers: JSON array of issue numbers (for issue source)
    - tags: JSON array of tags/labels
    - version: Version number
    - build_system: Build system type (maven|gradle|gradle-kotlin)
    - is_maven: Boolean indicating if Maven is used
    """

    @property
    def metadata(self) -> GeneratorMetadata:
        return GeneratorMetadata(
            name="dpaia_jvm",
            required_fields=[
                FieldDescriptor("description", description="PR/Issue body text (used as problem statement)"),
                FieldDescriptor("base_commit", description="Base commit SHA to checkout"),
                FieldDescriptor("patch", description="The diff/patch that fixes the issue"),
                FieldDescriptor("repo_url", description="Repository clone URL"),
            ],
            optional_fields=[
                FieldDescriptor("instance_id", required=False, description="Original instance_id from metadata block"),
                FieldDescriptor("title", required=False, description="PR/Issue title (prepended to problem statement)"),
                FieldDescriptor("FAIL_TO_PASS", required=False, description="Tests that should fail before fix and pass after"),
                FieldDescriptor("PASS_TO_PASS", required=False, description="Tests that should always pass"),
                FieldDescriptor("hints_text", required=False, description="Optional hints for solving the problem"),
                FieldDescriptor("number", required=False, description="Issue/PR number"),
                FieldDescriptor("labels", required=False, description="Issue/PR labels"),
                FieldDescriptor("test_patch", required=False, description="Test-only diff (separated from main patch)"),
                FieldDescriptor("repo_tree", required=False, description="List of files in the repository"),
                FieldDescriptor("build_system", required=False, description="Build system type (maven|gradle|gradle-kotlin)"),
            ],
        )

    def generate(
        self, provider: Provider, context: Context
    ) -> Iterator[dict[str, Any]]:
        """Generate DPAIA dataset records.

        .. deprecated::
            Use :class:`~ee_bench_dpaia.unified_generator.EEBenchCodegenGenerator` instead.

        Args:
            provider: The data provider to fetch fields from.
            context: Runtime context with selection and options.

        Yields:
            DPAIA-format dataset records.
        """
        warnings.warn(
            "DpaiaJvmGenerator is deprecated, use EEBenchCodegenGenerator instead",
            DeprecationWarning,
            stacklevel=2,
        )
        for item in provider.iter_items(context):
            item_context = Context(
                selection=context.selection,
                options=context.options,
                current_item=item,
            )

            owner = item.get("owner", "unknown")
            repo = item.get("repo", "unknown")
            number = item.get("number", 0)

            # instance_id: metadata first, then fallback
            instance_id = self._get(provider, "instance_id", item_context, "")
            if not instance_id:
                instance_id = f"{owner}__{repo}__{number}"

            # Required fields (source-less — routed by CompositeProvider)
            description = self._get(provider, "description", item_context, "")
            base_commit = self._get(provider, "base_commit", item_context, "")
            patch = self._get(provider, "patch", item_context, "")
            repo_url = self._get(provider, "repo_url", item_context, "")

            # Optional fields
            title = self._get(provider, "title", item_context, "")
            fail_to_pass = self._get(provider, "FAIL_TO_PASS", item_context, "[]")
            pass_to_pass = self._get(provider, "PASS_TO_PASS", item_context, "[]")
            hints_text = self._get(provider, "hints_text", item_context, "")
            labels = self._get(provider, "labels", item_context, [])
            test_patch = self._get(provider, "test_patch", item_context, "")
            build_system = self._get(provider, "build_system", item_context, "")

            # Build problem statement (title + description)
            problem_statement = (
                f"{title}\n\n{description}" if title and description
                else title or description or ""
            )

            version = context.options.get("version", "1")
            common_labels = context.options.get("common_labels", [])
            tags = [label for label in labels if label not in common_labels]

            yield {
                "instance_id": instance_id,
                "issue_numbers": json.dumps([str(number)]),
                "tags": json.dumps(tags),
                "repo": repo_url,
                "base_commit": base_commit,
                "patch": patch,
                "test_patch": test_patch,
                "problem_statement": problem_statement,
                "hints_text": hints_text,
                "FAIL_TO_PASS": fail_to_pass,
                "PASS_TO_PASS": pass_to_pass,
                "created_at": now_iso8601_utc(),
                "version": str(version),
                "build_system": build_system,
                "is_maven": build_system == "maven",
            }

    @staticmethod
    def _get(provider: Provider, name: str, context: Context, default: Any) -> Any:
        """Get a field by name (source-less), returning *default* on failure."""
        if provider.metadata.can_provide(name, ""):
            try:
                value = provider.get_field(name, "", context)
                if value is not None:
                    return value
            except Exception:
                pass
        return default


class DpaiaSweProGenerator(Generator):
    """Generator that produces records matching the original SWE-bench Pro dataset schema.

    Unlike `DpaiaJvmGenerator` (which is JVM-oriented and loses some fields),
    this generator round-trips **all** original SWE-bench Pro metadata fields
    that were embedded during import.

    Fields are declared without sources so they match any provider that
    supplies a field with the same name.
    """

    @property
    def metadata(self) -> GeneratorMetadata:
        return GeneratorMetadata(
            name="dpaia_swe_pro",
            required_fields=[
                FieldDescriptor("description", description="PR body text (used as problem statement)"),
                FieldDescriptor("patch", description="Source-only diff (from patch_splitter)"),
                FieldDescriptor("repo_url", description="Repository clone URL"),
            ],
            optional_fields=[
                FieldDescriptor("title", required=False, description="PR title (prepended to problem statement)"),
                FieldDescriptor("instance_id", required=False, description="Original instance_id from metadata block"),
                FieldDescriptor("hints_text", required=False, description="Hints section from PR body"),
                FieldDescriptor("test_patch", required=False, description="Test-only diff (from patch_splitter)"),
                *(
                    FieldDescriptor(
                        name,
                        required=False,
                        description=f"SWE-bench Pro metadata field '{name}'",
                    )
                    for name in _SWE_PRO_METADATA_FIELDS
                ),
            ],
        )

    def generate(
        self, provider: Provider, context: Context
    ) -> Iterator[dict[str, Any]]:
        warnings.warn(
            "DpaiaSweProGenerator is deprecated, use EEBenchCodegenGenerator instead",
            DeprecationWarning,
            stacklevel=2,
        )
        for item in provider.iter_items(context):
            item_context = Context(
                selection=context.selection,
                options=context.options,
                current_item=item,
            )

            owner = item.get("owner", "unknown")
            repo_name = item.get("repo", "unknown")
            number = item.get("number", 0)

            def _get(name: str, default: Any = "") -> Any:
                if provider.metadata.can_provide(name, ""):
                    try:
                        value = provider.get_field(name, "", item_context)
                        if value is not None:
                            return value
                    except Exception:
                        pass
                return default

            # instance_id: metadata first, then fallback
            instance_id = _get("instance_id") or f"{owner}__{repo_name}__{number}"

            # problem_statement = title + description
            title = _get("title")
            description = _get("description")
            problem_statement = (
                f"{title}\n\n{description}" if title and description
                else title or description or ""
            )

            patch = _get("patch")
            test_patch = _get("test_patch")

            # repo: prefer metadata `repo` (original owner/name), fall back to repo_url
            repo = _get("repo") or _get("repo_url")

            base_commit = _get("base_commit")
            created_at = _get("created_at") or now_iso8601_utc()

            yield {
                "instance_id": instance_id,
                "patch": patch,
                "test_patch": test_patch,
                "problem_statement": problem_statement,
                "hints_text": _get("hints_text"),
                "repo": repo,
                "base_commit": base_commit,
                "version": _get("version"),
                "repo_language": _get("repo_language"),
                "FAIL_TO_PASS": _get("FAIL_TO_PASS", default="[]"),
                "PASS_TO_PASS": _get("PASS_TO_PASS", default="[]"),
                "environment_setup_commit": _get("environment_setup_commit"),
                "requirements": _get("requirements"),
                "interface": _get("interface"),
                "issue_specificity": _get("issue_specificity"),
                "issue_categories": _get("issue_categories"),
                "dockerhub_tag": _get("dockerhub_tag"),
                "before_repo_set_cmd": _get("before_repo_set_cmd"),
                "selected_test_files_to_run": _get("selected_test_files_to_run"),
                "created_at": created_at,
                "checksum": _get("checksum"),
                "dataset": _get("dataset"),
                "run_script_name": _get("run_script_name"),
                "parser_name": _get("parser_name"),
            }
