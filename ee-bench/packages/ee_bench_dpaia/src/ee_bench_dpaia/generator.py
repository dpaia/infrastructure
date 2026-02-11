"""DPAIA Generator implementations."""

from __future__ import annotations

import json
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
]


class DpaiaJvmGenerator(Generator):
    """Generator that produces DPAIA-format dataset records for JVM projects.

    This generator creates records compatible with the SWE-bench evaluation
    framework, specifically designed for Java/JVM codebases.

    Supports both pull_request and issue sources. The generator will try
    pull_request source first, then fall back to issue source for each field.

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
                # Required fields can come from either pull_request or issue
                FieldDescriptor(
                    "description",
                    source="pull_request",
                    description="PR/Issue body text (used as problem statement)",
                ),
                FieldDescriptor(
                    "description",
                    source="issue",
                    description="Issue body text (used as problem statement)",
                ),
                FieldDescriptor(
                    "base_commit",
                    source="pull_request",
                    description="Base commit SHA to checkout",
                ),
                FieldDescriptor(
                    "base_commit",
                    source="issue",
                    description="Base commit SHA (from linked commits)",
                ),
                FieldDescriptor(
                    "patch",
                    source="pull_request",
                    description="The diff/patch that fixes the issue",
                ),
                FieldDescriptor(
                    "patch",
                    source="issue",
                    description="Combined diff from linked commits",
                ),
                FieldDescriptor(
                    "repo_url",
                    source="repository",
                    description="Repository clone URL",
                ),
            ],
            optional_fields=[
                # instance_id from metadata enrichment (overrides generated id)
                FieldDescriptor(
                    "instance_id",
                    source="pull_request",
                    required=False,
                    description="Original instance_id from metadata block",
                ),
                # Optional fields from pull_request
                FieldDescriptor(
                    "title",
                    source="pull_request",
                    required=False,
                    description="PR title (prepended to problem statement)",
                ),
                FieldDescriptor(
                    "FAIL_TO_PASS",
                    source="pull_request",
                    required=False,
                    description="Tests that should fail before fix and pass after",
                ),
                FieldDescriptor(
                    "PASS_TO_PASS",
                    source="pull_request",
                    required=False,
                    description="Tests that should always pass",
                ),
                FieldDescriptor(
                    "hints_text",
                    source="pull_request",
                    required=False,
                    description="Optional hints for solving the problem",
                ),
                # Optional fields from issue
                FieldDescriptor(
                    "title",
                    source="issue",
                    required=False,
                    description="Issue title (prepended to problem statement)",
                ),
                FieldDescriptor(
                    "FAIL_TO_PASS",
                    source="issue",
                    required=False,
                    description="Tests from issue body/comments",
                ),
                FieldDescriptor(
                    "PASS_TO_PASS",
                    source="issue",
                    required=False,
                    description="Tests from issue body/comments",
                ),
                FieldDescriptor(
                    "number",
                    source="issue",
                    required=False,
                    description="Issue number",
                ),
                FieldDescriptor(
                    "labels",
                    source="issue",
                    required=False,
                    description="Issue labels",
                ),
                FieldDescriptor(
                    "test_patch",
                    source="pull_request",
                    required=False,
                    description="Test-only diff (separated from main patch)",
                ),
                FieldDescriptor(
                    "test_patch",
                    source="issue",
                    required=False,
                    description="Test-only diff (separated from main patch)",
                ),
                # Repository fields
                FieldDescriptor(
                    "repo_tree",
                    source="repository",
                    required=False,
                    description="List of files in the repository",
                ),
                FieldDescriptor(
                    "build_system",
                    source="repository",
                    required=False,
                    description="Build system type (maven|gradle|gradle-kotlin)",
                ),
            ],
        )

    def output_schema(self) -> dict[str, Any]:
        """Return JSON Schema for DPAIA output records."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "title": "DPAIA JVM Dataset Record",
            "description": "A single record in the DPAIA JVM evaluation dataset",
            "required": [
                "instance_id",
                "repo",
                "base_commit",
                "patch",
                "problem_statement",
                "FAIL_TO_PASS",
                "PASS_TO_PASS",
                "created_at",
            ],
            "properties": {
                "instance_id": {
                    "type": "string",
                    "description": "Unique identifier in format owner__repo__number",
                    "pattern": "^[a-zA-Z0-9_-]+__[a-zA-Z0-9_.-]+__\\d+$",
                },
                "issue_numbers": {
                    "type": "string",
                    "description": "JSON array of issue numbers",
                },
                "tags": {
                    "type": "string",
                    "description": "JSON array of tags/labels",
                },
                "repo": {
                    "type": "string",
                    "description": "Repository clone URL",
                    "format": "uri",
                },
                "base_commit": {
                    "type": "string",
                    "description": "Commit SHA to checkout before applying patch",
                    "pattern": "^[a-f0-9]{40}$",
                },
                "patch": {
                    "type": "string",
                    "description": "Unified diff that fixes the issue",
                },
                "test_patch": {
                    "type": "string",
                    "description": "Unified diff for test files (if separated)",
                },
                "problem_statement": {
                    "type": "string",
                    "description": "Description of the problem to solve",
                },
                "hints_text": {
                    "type": "string",
                    "description": "Optional hints for solving the problem",
                },
                "FAIL_TO_PASS": {
                    "type": "string",
                    "description": "JSON array of test identifiers that should fail then pass",
                },
                "PASS_TO_PASS": {
                    "type": "string",
                    "description": "JSON array of test identifiers that should always pass",
                },
                "created_at": {
                    "type": "string",
                    "description": "ISO8601 timestamp when record was generated",
                    "format": "date-time",
                },
                "version": {
                    "type": "string",
                    "description": "Version number of the record",
                },
                "build_system": {
                    "type": "string",
                    "description": "Build system type (maven|gradle|gradle-kotlin)",
                    "enum": ["maven", "gradle", "gradle-kotlin", ""],
                },
                "is_maven": {
                    "type": "boolean",
                    "description": "Whether the project uses Maven",
                },
            },
            "additionalProperties": True,
        }

    def generate(
        self, provider: Provider, context: Context
    ) -> Iterator[dict[str, Any]]:
        """Generate DPAIA dataset records.

        Args:
            provider: The data provider to fetch fields from.
            context: Runtime context with selection and options.

        Yields:
            DPAIA-format dataset records.
        """
        # Determine primary source based on provider capabilities
        primary_source = self._determine_primary_source(provider)

        for item in provider.iter_items(context):
            # Update context with current item
            item_context = Context(
                selection=context.selection,
                options=context.options,
                current_item=item,
            )

            # Extract item-level info (needed for fallback instance_id and issue_numbers)
            owner = item.get("owner", "unknown")
            repo = item.get("repo", "unknown")
            number = item.get("number", 0)

            # Try to get instance_id from metadata, fall back to generated
            instance_id = self._get_field_with_fallback(
                provider, "instance_id", primary_source, item_context, ""
            )
            if not instance_id:
                instance_id = f"{owner}__{repo}__{number}"

            # Fetch required fields (try primary source first, then fallback)
            description = self._get_field_with_fallback(
                provider, "description", primary_source, item_context, ""
            )
            base_commit = self._get_field_with_fallback(
                provider, "base_commit", primary_source, item_context, ""
            )
            patch = self._get_field_with_fallback(
                provider, "patch", primary_source, item_context, ""
            )
            repo_url = provider.get_field("repo_url", "repository", item_context)

            # Fetch optional fields with defaults
            title = self._get_field_with_fallback(
                provider, "title", primary_source, item_context, ""
            )
            fail_to_pass = self._get_field_with_fallback(
                provider, "FAIL_TO_PASS", primary_source, item_context, "[]"
            )
            pass_to_pass = self._get_field_with_fallback(
                provider, "PASS_TO_PASS", primary_source, item_context, "[]"
            )
            hints_text = self._get_optional_field(
                provider, "hints_text", primary_source, item_context, ""
            )

            # Get labels for tags (from issue source)
            labels = self._get_optional_field(
                provider, "labels", "issue", item_context, []
            )

            # Fetch test_patch (may come from a patch splitter enrichment provider)
            test_patch = self._get_field_with_fallback(
                provider, "test_patch", primary_source, item_context, ""
            )

            # Get build system
            build_system = self._get_optional_field(
                provider, "build_system", "repository", item_context, ""
            )

            # Build problem statement (title + description)
            problem_statement = self._build_problem_statement(title, description)

            # Get version from generator options
            version = context.options.get("version", "1")

            # Filter out common labels for tags
            common_labels = context.options.get("common_labels", [])
            tags = [label for label in labels if label not in common_labels]

            record = {
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

            yield record

    def _determine_primary_source(self, provider: Provider) -> str:
        """Determine the primary source based on provider capabilities.

        Returns 'issue' if provider can provide issue fields,
        otherwise returns 'pull_request'.
        """
        # Check if provider can provide issue-specific fields
        if provider.metadata.can_provide("base_commit", "issue"):
            return "issue"
        return "pull_request"

    def _get_field_with_fallback(
        self,
        provider: Provider,
        name: str,
        primary_source: str,
        context: Context,
        default: Any,
    ) -> Any:
        """Get a field, trying primary source first, then fallback source."""
        fallback_source = "issue" if primary_source == "pull_request" else "pull_request"

        # Try primary source first
        if provider.metadata.can_provide(name, primary_source):
            try:
                value = provider.get_field(name, primary_source, context)
                if value:  # Return if non-empty
                    return value
            except Exception:
                pass

        # Try fallback source
        if provider.metadata.can_provide(name, fallback_source):
            try:
                value = provider.get_field(name, fallback_source, context)
                if value:
                    return value
            except Exception:
                pass

        return default

    def _get_optional_field(
        self,
        provider: Provider,
        name: str,
        source: str,
        context: Context,
        default: Any,
    ) -> Any:
        """Get an optional field, returning default if not available."""
        if provider.metadata.can_provide(name, source):
            try:
                return provider.get_field(name, source, context)
            except Exception:
                return default
        return default

    def _build_problem_statement(self, title: str, description: str) -> str:
        """Build problem statement from title and description."""
        if title and description:
            return f"{title}\n\n{description}"
        return title or description or ""


class DpaiaSweProGenerator(Generator):
    """Generator that produces records matching the original SWE-bench Pro dataset schema.

    Unlike `DpaiaJvmGenerator` (which is JVM-oriented and loses some fields),
    this generator round-trips **all** original SWE-bench Pro metadata fields
    that were embedded during import.

    All metadata fields are declared with ``source="pull_request"`` because
    :class:`MetadataProvider` exposes them under that source by default.
    """

    @property
    def metadata(self) -> GeneratorMetadata:
        return GeneratorMetadata(
            name="dpaia_swe_pro",
            required_fields=[
                FieldDescriptor(
                    "description",
                    source="pull_request",
                    description="PR body text (used as problem statement)",
                ),
                FieldDescriptor(
                    "patch",
                    source="pull_request",
                    description="Source-only diff (from patch_splitter)",
                ),
                FieldDescriptor(
                    "repo_url",
                    source="repository",
                    description="Repository clone URL",
                ),
            ],
            optional_fields=[
                FieldDescriptor(
                    "title",
                    source="pull_request",
                    required=False,
                    description="PR title (prepended to problem statement)",
                ),
                FieldDescriptor(
                    "instance_id",
                    source="pull_request",
                    required=False,
                    description="Original instance_id from metadata block",
                ),
                FieldDescriptor(
                    "hints_text",
                    source="pull_request",
                    required=False,
                    description="Hints section from PR body",
                ),
                FieldDescriptor(
                    "test_patch",
                    source="pull_request",
                    required=False,
                    description="Test-only diff (from patch_splitter)",
                ),
                # All SWE-bench Pro metadata fields
                *(
                    FieldDescriptor(
                        name,
                        source="pull_request",
                        required=False,
                        description=f"SWE-bench Pro metadata field '{name}'",
                    )
                    for name in _SWE_PRO_METADATA_FIELDS
                ),
            ],
        )

    def output_schema(self) -> dict[str, Any]:
        """Return JSON Schema for SWE-bench Pro output records."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "title": "SWE-bench Pro Dataset Record",
            "description": "A single record matching the original SWE-bench Pro schema",
            "required": [
                "instance_id",
                "patch",
                "problem_statement",
                "repo",
                "base_commit",
            ],
            "properties": {
                "instance_id": {"type": "string"},
                "patch": {"type": "string"},
                "test_patch": {"type": "string"},
                "problem_statement": {"type": "string"},
                "hints_text": {"type": "string"},
                "repo": {"type": "string"},
                "base_commit": {"type": "string"},
                "version": {"type": "string"},
                "repo_language": {"type": "string"},
                "FAIL_TO_PASS": {"type": "string"},
                "PASS_TO_PASS": {"type": "string"},
                "environment_setup_commit": {"type": "string"},
                "requirements": {"type": "string"},
                "interface": {"type": "string"},
                "issue_specificity": {"type": "string"},
                "issue_categories": {"type": "string"},
                "dockerhub_tag": {"type": "string"},
                "before_repo_set_cmd": {"type": "string"},
                "selected_test_files_to_run": {"type": "string"},
                "created_at": {"type": "string", "format": "date-time"},
                "checksum": {"type": "string"},
                "dataset": {"type": "string"},
            },
            "additionalProperties": False,
        }

    def generate(
        self, provider: Provider, context: Context
    ) -> Iterator[dict[str, Any]]:
        for item in provider.iter_items(context):
            item_context = Context(
                selection=context.selection,
                options=context.options,
                current_item=item,
            )

            owner = item.get("owner", "unknown")
            repo_name = item.get("repo", "unknown")
            number = item.get("number", 0)

            # --- helpers ---
            def _get(name: str, source: str = "pull_request", default: Any = "") -> Any:
                if provider.metadata.can_provide(name, source):
                    try:
                        value = provider.get_field(name, source, item_context)
                        if value is not None:
                            return value
                    except Exception:
                        pass
                return default

            # instance_id: metadata first, then fallback
            instance_id = _get("instance_id") or f"{owner}__{repo_name}__{number}"

            # problem_statement = title + description (metadata block already stripped by MetadataProvider)
            title = _get("title")
            description = _get("description")
            problem_statement = (
                f"{title}\n\n{description}" if title and description
                else title or description or ""
            )

            # patch / test_patch from provider (patch_splitter splits them)
            patch = _get("patch")
            test_patch = _get("test_patch")

            # repo: prefer metadata `repo` (original owner/name), fall back to repo_url
            repo = _get("repo") or _get("repo_url", source="repository")

            # base_commit: prefer metadata
            base_commit = _get("base_commit")

            # created_at: prefer metadata, otherwise generate new
            created_at = _get("created_at") or now_iso8601_utc()

            record: dict[str, Any] = {
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
            }

            yield record
