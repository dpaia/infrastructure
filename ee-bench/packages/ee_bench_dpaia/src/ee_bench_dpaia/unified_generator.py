"""Unified EE-bench codegen generator."""

from __future__ import annotations

import json
from typing import Any, Iterator

from ee_bench_generator import Generator, Provider
from ee_bench_generator.clock import now_iso8601_utc
from ee_bench_generator.metadata import Context, FieldDescriptor, GeneratorMetadata
from ee_bench_generator.tag_utils import filter_tags


class EEBenchCodegenGenerator(Generator):
    """Unified generator for EE-bench codegen dataset records.

    Replaces both ``DpaiaJvmGenerator`` and ``DpaiaSweProGenerator``
    with a single generator that:

    - Declares all known fields (JVM + SWE-bench Pro) as required/optional
    - Relies on ``SectionProvider`` for ``problem_statement`` extraction
    - Relies on ``MetadataProvider`` (auto mode) for dynamic metadata
    - Collects extra metadata fields via ``provider.get_extra_fields()``

    No metadata parsing or section extraction happens here — all parsing
    logic lives in providers.
    """

    @property
    def metadata(self) -> GeneratorMetadata:
        return GeneratorMetadata(
            name="ee_bench_codegen",
            required_fields=[
                FieldDescriptor("description", description="Issue/PR body text"),
                FieldDescriptor("patch", description="Source-only diff"),
                FieldDescriptor("repo_url", description="Repository clone URL"),
            ],
            optional_fields=[
                FieldDescriptor("problem_statement", required=False, description="Extracted problem statement (from markdown_sections provider)"),
                FieldDescriptor("instance_id", required=False, description="Unique instance identifier"),
                FieldDescriptor("title", required=False, description="Issue/PR title (prepended to problem_statement when no sections provider)"),
                FieldDescriptor("base_commit", required=False, description="Base commit SHA"),
                FieldDescriptor("labels", required=False, description="Issue/PR labels"),
                FieldDescriptor("test_patch", required=False, description="Test-only diff"),
                FieldDescriptor("hints_text", required=False, description="Hints for solving the problem"),
                FieldDescriptor("FAIL_TO_PASS", required=False, description="Tests that should fail before fix and pass after"),
                FieldDescriptor("PASS_TO_PASS", required=False, description="Tests that should always pass"),
                FieldDescriptor("build_system", required=False, description="Build system type (maven|gradle|gradle-kotlin)"),
                FieldDescriptor("repo", required=False, description="Original owner/name (e.g. 'apache/kafka')"),
                FieldDescriptor("version", required=False, description="Version number"),
                FieldDescriptor("repo_language", required=False, description="Primary repository language"),
                FieldDescriptor("environment_setup_commit", required=False, description="Commit for environment setup"),
                FieldDescriptor("requirements", required=False, description="Requirements section content"),
                FieldDescriptor("interface", required=False, description="Interface section content"),
                FieldDescriptor("issue_specificity", required=False, description="Issue specificity categories"),
                FieldDescriptor("issue_categories", required=False, description="Issue categories"),
                FieldDescriptor("dockerhub_tag", required=False, description="Docker Hub tag for the environment"),
                FieldDescriptor("before_repo_set_cmd", required=False, description="Command to run before repo setup"),
                FieldDescriptor("selected_test_files_to_run", required=False, description="Test files to run"),
                FieldDescriptor("created_at", required=False, description="ISO8601 creation timestamp"),
                FieldDescriptor("checksum", required=False, description="Checksum of the original record"),
                FieldDescriptor("dataset", required=False, description="Dataset name/identifier"),
                FieldDescriptor("run_script_name", required=False, description="Run script name"),
                FieldDescriptor("parser_name", required=False, description="Parser name"),
            ],
        )

    def generate(
        self, provider: Provider, context: Context
    ) -> Iterator[dict[str, Any]]:
        """Generate unified EE-bench codegen dataset records.

        Args:
            provider: The data provider to fetch fields from.
            context: Runtime context with selection and options.

        Yields:
            Dataset records as dictionaries.
        """
        # Generator options may be nested under "generator_options" (CLI path)
        # or flat in context.options (test / direct-call path).
        opts = context.options.get("generator_options", context.options)
        skip_empty = opts.get("skip_empty_fields", True)

        for item in provider.iter_items(context):
            item_context = Context(
                selection=context.selection,
                options=context.options,
                current_item=item,
            )

            owner = item.get("owner", "unknown")
            repo_name = item.get("repo", "unknown")
            number = item.get("number", 0)

            # instance_id: provider first, then fallback
            instance_id = _get(provider, "instance_id", item_context, "")
            if not instance_id:
                safe_repo = repo_name.replace("-", "__")
                instance_id = f"{owner}__{safe_repo}-{number}"

            # problem_statement: prefer extracted section, fall back to description
            problem_statement = _get(provider, "problem_statement", item_context, "")
            if not problem_statement:
                problem_statement = _get(provider, "description", item_context, "")

            patch = _get(provider, "patch", item_context, "")
            repo_url = _get(provider, "repo_url", item_context, "")

            # repo: prefer metadata `repo`, fall back to repo_url (stripped)
            repo = _get(provider, "repo", item_context, "")
            if not repo and repo_url:
                repo = repo_url.removeprefix("https://github.com/").removeprefix("http://github.com/")

            # created_at: prefer provider, fall back to now
            created_at = _get(provider, "created_at", item_context, "") or now_iso8601_utc()

            # Version from provider or context options
            version = _get(provider, "version", item_context, "")
            if not version:
                version = str(opts.get("version", ""))

            # JVM-specific fields
            build_system = _get(provider, "build_system", item_context, "")
            labels = _get(provider, "labels", item_context, [])
            tags_cfg = opts.get("tags", {})
            # Backward compat: fall back to flat "exclude" if no tags section
            exclude_patterns = tags_cfg.get("exclude") or opts.get("exclude", [])
            include_patterns = tags_cfg.get("include", [])
            tags = filter_tags(labels, exclude=exclude_patterns, include=include_patterns) if isinstance(labels, list) else labels

            record: dict[str, Any] = {
                "instance_id": instance_id,
                "patch": patch,
                "test_patch": _get(provider, "test_patch", item_context, ""),
                "problem_statement": problem_statement,
                "hints_text": _get(provider, "hints_text", item_context, ""),
                "repo": repo,
                "base_commit": _get(provider, "base_commit", item_context, ""),
                "version": version,
                "repo_language": _get(provider, "repo_language", item_context, ""),
                "FAIL_TO_PASS": _get(provider, "FAIL_TO_PASS", item_context, "[]"),
                "PASS_TO_PASS": _get(provider, "PASS_TO_PASS", item_context, "[]"),
                "environment_setup_commit": _get(provider, "environment_setup_commit", item_context, ""),
                "requirements": _get(provider, "requirements", item_context, ""),
                "interface": _get(provider, "interface", item_context, ""),
                "issue_specificity": _get(provider, "issue_specificity", item_context, ""),
                "issue_categories": _get(provider, "issue_categories", item_context, ""),
                "dockerhub_tag": _get(provider, "dockerhub_tag", item_context, ""),
                "before_repo_set_cmd": _get(provider, "before_repo_set_cmd", item_context, ""),
                "selected_test_files_to_run": _get(provider, "selected_test_files_to_run", item_context, ""),
                "created_at": created_at,
                "checksum": _get(provider, "checksum", item_context, ""),
                "dataset": _get(provider, "dataset", item_context, ""),
                "run_script_name": _get(provider, "run_script_name", item_context, ""),
                "parser_name": _get(provider, "parser_name", item_context, ""),
                # JVM fields
                "build_system": build_system,
                "is_maven": _get(provider, "is_maven", item_context, build_system == "maven"),
                "issue_numbers": json.dumps([str(number)]),
                "tags": json.dumps(tags) if isinstance(tags, list) else tags,
            }

            # Collect extra fields from wildcard providers
            if hasattr(provider, "get_extra_fields"):
                extras = provider.get_extra_fields(item_context)
                for key, value in extras.items():
                    if key not in record:
                        record[key] = value

            if skip_empty:
                record = {k: v for k, v in record.items() if v != ""}

            yield record


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
