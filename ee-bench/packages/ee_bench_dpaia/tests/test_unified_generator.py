"""Tests for EEBenchCodegenGenerator (unified generator)."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from ee_bench_generator.metadata import Context, FieldDescriptor, ProviderMetadata, Selection

from ee_bench_dpaia import EEBenchCodegenGenerator


@pytest.fixture
def generator():
    return EEBenchCodegenGenerator()


@pytest.fixture
def context():
    return Context(
        selection=Selection(
            resource="pull_requests",
            filters={"repo": "owner/repo", "pr_numbers": [42]},
        )
    )


def _make_provider(
    field_values: dict,
    items: list[dict],
    extra_fields: list[FieldDescriptor] | None = None,
    *,
    wildcard: bool = False,
    extra_field_values: dict | None = None,
) -> MagicMock:
    """Create a mock provider with specified fields and items."""
    provider = MagicMock()

    provided_fields = [
        FieldDescriptor("description", "pull_request"),
        FieldDescriptor("patch", "pull_request"),
        FieldDescriptor("repo_url", "repository"),
    ]
    if extra_fields:
        provided_fields.extend(extra_fields)

    provider.metadata = ProviderMetadata(
        name="mock_provider",
        sources=["pull_request", "repository"],
        provided_fields=provided_fields,
        wildcard=wildcard,
    )

    def get_field(name, source, ctx):
        return field_values.get(name)

    provider.get_field.side_effect = get_field
    provider.iter_items.return_value = iter(items)

    if extra_field_values is not None:
        provider.get_extra_fields.return_value = extra_field_values
    else:
        # No get_extra_fields by default
        del provider.get_extra_fields

    return provider


# ---------------------------------------------------------------------------
# Metadata tests
# ---------------------------------------------------------------------------


class TestEEBenchCodegenGeneratorMetadata:
    def test_metadata_name(self, generator):
        assert generator.metadata.name == "ee_bench_codegen"

    def test_required_fields(self, generator):
        required_names = {f.name for f in generator.metadata.required_fields}
        assert "description" in required_names
        assert "patch" in required_names
        assert "repo_url" in required_names

    def test_optional_fields_include_all_known(self, generator):
        optional_names = {f.name for f in generator.metadata.optional_fields}
        for field in [
            "problem_statement", "instance_id", "title",
            "base_commit", "labels", "test_patch",
            "hints_text", "FAIL_TO_PASS", "PASS_TO_PASS",
            "build_system", "repo", "version", "repo_language",
            "environment_setup_commit", "requirements", "interface",
            "issue_specificity", "issue_categories", "dockerhub_tag",
            "before_repo_set_cmd", "selected_test_files_to_run",
            "created_at", "checksum", "dataset", "run_script_name",
            "parser_name",
        ]:
            assert field in optional_names, f"Missing optional field: {field}"


# ---------------------------------------------------------------------------
# Core record generation
# ---------------------------------------------------------------------------


class TestEEBenchCodegenGeneratorGenerate:
    def test_generates_record_with_core_fields(self, generator, context):
        provider = _make_provider(
            field_values={
                "description": "Fix the parser bug",
                "patch": "diff --git a/parser.py b/parser.py\n+fix",
                "repo_url": "https://github.com/owner/repo.git",
                "base_commit": "abc123",
            },
            items=[{"owner": "owner", "repo": "repo", "number": 42}],
            extra_fields=[FieldDescriptor("base_commit", "pull_request")],
        )
        records = list(generator.generate(provider, context))
        assert len(records) == 1
        r = records[0]
        assert r["problem_statement"] == "Fix the parser bug"
        assert "diff --git" in r["patch"]
        assert r["repo"] == "owner/repo.git"
        assert r["base_commit"] == "abc123"

    def test_problem_statement_from_sections_provider(self, generator, context):
        """When problem_statement is provided (e.g. by markdown_sections), use it directly."""
        provider = _make_provider(
            field_values={
                "description": "Full body with ## headers and metadata",
                "problem_statement": "Extracted problem statement",
                "patch": "diff",
                "repo_url": "https://github.com/o/r.git",
            },
            items=[{"owner": "o", "repo": "r", "number": 1}],
            extra_fields=[FieldDescriptor("problem_statement", "pull_request")],
        )
        records = list(generator.generate(provider, context))
        assert records[0]["problem_statement"] == "Extracted problem statement"

    def test_instance_id_from_provider(self, generator, context):
        provider = _make_provider(
            field_values={
                "description": "desc",
                "patch": "diff",
                "repo_url": "https://github.com/o/r.git",
                "instance_id": "custom__instance__id",
            },
            items=[{"owner": "o", "repo": "r", "number": 1}],
            extra_fields=[FieldDescriptor("instance_id", "pull_request")],
        )
        records = list(generator.generate(provider, context))
        assert records[0]["instance_id"] == "custom__instance__id"

    def test_instance_id_fallback(self, generator, context):
        provider = _make_provider(
            field_values={
                "description": "desc",
                "patch": "diff",
                "repo_url": "https://github.com/myorg/myrepo.git",
            },
            items=[{"owner": "myorg", "repo": "myrepo", "number": 99}],
        )
        records = list(generator.generate(provider, context))
        assert records[0]["instance_id"] == "myorg__myrepo-99"

    def test_instance_id_fallback_hyphens_replaced(self, generator, context):
        """Hyphens in repo name are replaced with double underscores."""
        provider = _make_provider(
            field_values={
                "description": "desc",
                "patch": "diff",
                "repo_url": "https://github.com/dpaia/spring-boot-microshop.git",
            },
            items=[{"owner": "dpaia", "repo": "spring-boot-microshop", "number": 1}],
        )
        records = list(generator.generate(provider, context))
        assert records[0]["instance_id"] == "dpaia__spring__boot__microshop-1"

    def test_repo_fallback_to_repo_url(self, generator, context):
        provider = _make_provider(
            field_values={
                "description": "desc",
                "patch": "diff",
                "repo_url": "https://github.com/o/r.git",
            },
            items=[{"owner": "o", "repo": "r", "number": 1}],
        )
        records = list(generator.generate(provider, context))
        assert records[0]["repo"] == "o/r.git"

    def test_repo_from_provider(self, generator, context):
        provider = _make_provider(
            field_values={
                "description": "desc",
                "patch": "diff",
                "repo_url": "https://github.com/dpaia/webclients.git",
                "repo": "protonmail/webclients",
            },
            items=[{"owner": "dpaia", "repo": "webclients", "number": 1}],
            extra_fields=[FieldDescriptor("repo", "pull_request")],
        )
        records = list(generator.generate(provider, context))
        assert records[0]["repo"] == "protonmail/webclients"

    def test_created_at_from_provider(self, generator, context):
        provider = _make_provider(
            field_values={
                "description": "desc",
                "patch": "diff",
                "repo_url": "https://github.com/o/r.git",
                "created_at": "2025-01-15T10:30:00+00:00",
            },
            items=[{"owner": "o", "repo": "r", "number": 1}],
            extra_fields=[FieldDescriptor("created_at", "pull_request")],
        )
        records = list(generator.generate(provider, context))
        assert records[0]["created_at"] == "2025-01-15T10:30:00+00:00"

    def test_created_at_fallback_generates_timestamp(self, generator, context):
        provider = _make_provider(
            field_values={
                "description": "desc",
                "patch": "diff",
                "repo_url": "https://github.com/o/r.git",
            },
            items=[{"owner": "o", "repo": "r", "number": 1}],
        )
        records = list(generator.generate(provider, context))
        ts = records[0]["created_at"]
        assert ts.endswith("Z") or ts.endswith("+00:00")
        normalized = ts.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        assert parsed.tzinfo is not None

    def test_missing_optional_fields_omitted_by_default(self, generator, context):
        provider = _make_provider(
            field_values={
                "description": "desc",
                "patch": "diff",
                "repo_url": "https://github.com/o/r.git",
            },
            items=[{"owner": "o", "repo": "r", "number": 1}],
        )
        records = list(generator.generate(provider, context))
        r = records[0]
        # Non-empty defaults are kept
        assert r["FAIL_TO_PASS"] == "[]"
        assert r["PASS_TO_PASS"] == "[]"
        # Empty string fields are omitted
        assert "hints_text" not in r
        assert "repo_language" not in r
        assert "dockerhub_tag" not in r
        assert "dataset" not in r
        assert "test_patch" not in r

    def test_skip_empty_fields_false_keeps_all_fields(self, generator, context):
        context.options["skip_empty_fields"] = False
        provider = _make_provider(
            field_values={
                "description": "desc",
                "patch": "diff",
                "repo_url": "https://github.com/o/r.git",
            },
            items=[{"owner": "o", "repo": "r", "number": 1}],
        )
        records = list(generator.generate(provider, context))
        r = records[0]
        assert r["FAIL_TO_PASS"] == "[]"
        assert r["PASS_TO_PASS"] == "[]"
        assert r["hints_text"] == ""
        assert r["repo_language"] == ""
        assert r["dockerhub_tag"] == ""
        assert r["dataset"] == ""
        assert r["test_patch"] == ""

    def test_jvm_fields(self, generator, context):
        provider = _make_provider(
            field_values={
                "description": "desc",
                "patch": "diff",
                "repo_url": "https://github.com/o/r.git",
                "build_system": "maven",
                "labels": ["ee-bench-codegen", "bug"],
            },
            items=[{"owner": "o", "repo": "r", "number": 42}],
            extra_fields=[
                FieldDescriptor("build_system", "pull_request"),
                FieldDescriptor("labels", "pull_request"),
            ],
        )
        context.options["tags"] = {"exclude": ["ee-bench-codegen"]}
        records = list(generator.generate(provider, context))
        r = records[0]
        assert r["build_system"] == "maven"
        assert r["is_maven"] is True
        assert r["issue_numbers"] == json.dumps(["42"])
        assert json.loads(r["tags"]) == ["bug"]

    def test_problem_statement_fallback_to_description(self, generator, context):
        """When no problem_statement provider, fall back to description (body)."""
        provider = _make_provider(
            field_values={
                "description": "Fix null pointer exception in Parser",
                "patch": "diff",
                "repo_url": "https://github.com/o/r.git",
            },
            items=[{"owner": "o", "repo": "r", "number": 1}],
        )
        records = list(generator.generate(provider, context))
        assert records[0]["problem_statement"] == "Fix null pointer exception in Parser"

    def test_all_swe_bench_pro_fields_roundtrip(self, generator, context):
        field_values = {
            "description": "TypeError in crypto module",
            "problem_statement": "Extracted: TypeError in crypto module",
            "patch": "diff --git a/crypto.js b/crypto.js\n+fix",
            "repo_url": "https://github.com/dpaia/webclients.git",
            "instance_id": "protonmail__webclients__42",
            "test_patch": "diff --git a/test/crypto.test.js\n+test",
            "hints_text": "Check the key derivation function",
            "repo": "protonmail/webclients",
            "base_commit": "9b35b414" + "a" * 32,
            "version": "1.2.3",
            "repo_language": "js",
            "FAIL_TO_PASS": '["test/crypto.test.js::derivation"]',
            "PASS_TO_PASS": '["test/crypto.test.js::encrypt"]',
            "environment_setup_commit": "e" * 40,
            "requirements": "node>=18",
            "interface": "CryptoModule.derive()",
            "issue_specificity": '["crypto_feat"]',
            "issue_categories": '["security_knowledge"]',
            "dockerhub_tag": "protonmail.webclients-1.2.3",
            "before_repo_set_cmd": "git reset --hard HEAD",
            "selected_test_files_to_run": '["test/crypto.test.js"]',
            "created_at": "2025-01-15T10:30:00+00:00",
            "checksum": "abc123def",
            "dataset": "swe-bench-pro",
            "run_script_name": "run.sh",
            "parser_name": "default_parser",
        }
        extra_fields = [
            FieldDescriptor(name, "pull_request")
            for name in field_values
            if name not in ("description", "patch", "repo_url")
        ]
        provider = _make_provider(
            field_values=field_values,
            items=[{"owner": "dpaia", "repo": "webclients", "number": 7}],
            extra_fields=extra_fields,
        )
        records = list(generator.generate(provider, context))
        assert len(records) == 1
        r = records[0]
        assert r["problem_statement"] == "Extracted: TypeError in crypto module"
        assert r["instance_id"] == "protonmail__webclients__42"
        assert r["repo"] == "protonmail/webclients"
        assert r["base_commit"] == "9b35b414" + "a" * 32
        assert r["version"] == "1.2.3"
        assert r["repo_language"] == "js"
        assert r["FAIL_TO_PASS"] == '["test/crypto.test.js::derivation"]'
        assert r["PASS_TO_PASS"] == '["test/crypto.test.js::encrypt"]'
        assert r["environment_setup_commit"] == "e" * 40
        assert r["requirements"] == "node>=18"
        assert r["interface"] == "CryptoModule.derive()"
        assert r["issue_specificity"] == '["crypto_feat"]'
        assert r["issue_categories"] == '["security_knowledge"]'
        assert r["dockerhub_tag"] == "protonmail.webclients-1.2.3"
        assert r["before_repo_set_cmd"] == "git reset --hard HEAD"
        assert r["selected_test_files_to_run"] == '["test/crypto.test.js"]'
        assert r["created_at"] == "2025-01-15T10:30:00+00:00"
        assert r["checksum"] == "abc123def"
        assert r["dataset"] == "swe-bench-pro"
        assert r["run_script_name"] == "run.sh"
        assert r["parser_name"] == "default_parser"

    def test_multiple_items(self, generator, context):
        provider = _make_provider(
            field_values={
                "description": "desc",
                "patch": "diff",
                "repo_url": "https://github.com/o/r.git",
            },
            items=[
                {"owner": "o", "repo": "r", "number": 1},
                {"owner": "o", "repo": "r", "number": 2},
                {"owner": "o", "repo": "r", "number": 3},
            ],
        )
        records = list(generator.generate(provider, context))
        assert len(records) == 3
        assert records[0]["instance_id"] == "o__r-1"
        assert records[1]["instance_id"] == "o__r-2"
        assert records[2]["instance_id"] == "o__r-3"

    def test_empty_provider_yields_nothing(self, generator, context):
        provider = _make_provider(
            field_values={},
            items=[],
        )
        records = list(generator.generate(provider, context))
        assert records == []

    def test_extra_fields_from_wildcard_provider(self, generator, context):
        provider = _make_provider(
            field_values={
                "description": "desc",
                "patch": "diff",
                "repo_url": "https://github.com/o/r.git",
            },
            items=[{"owner": "o", "repo": "r", "number": 1}],
            wildcard=True,
            extra_field_values={
                "custom_field_1": "value1",
                "custom_field_2": "value2",
            },
        )
        records = list(generator.generate(provider, context))
        r = records[0]
        assert r["custom_field_1"] == "value1"
        assert r["custom_field_2"] == "value2"

    def test_extra_fields_do_not_override_known_fields(self, generator, context):
        """Extra fields from wildcard provider should not override already-set fields."""
        provider = _make_provider(
            field_values={
                "description": "real desc",
                "patch": "real diff",
                "repo_url": "https://github.com/o/r.git",
            },
            items=[{"owner": "o", "repo": "r", "number": 1}],
            wildcard=True,
            extra_field_values={
                "patch": "should NOT override",
                "new_field": "should appear",
            },
        )
        records = list(generator.generate(provider, context))
        r = records[0]
        assert r["patch"] == "real diff"
        assert r["new_field"] == "should appear"

    def test_tags_include_overrides_exclude(self, generator, context):
        """Include patterns override excluded labels."""
        provider = _make_provider(
            field_values={
                "description": "desc",
                "patch": "diff",
                "repo_url": "https://github.com/o/r.git",
                "labels": ["ee-bench-codegen", "bug", "Epic"],
            },
            items=[{"owner": "o", "repo": "r", "number": 1}],
            extra_fields=[FieldDescriptor("labels", "pull_request")],
        )
        context.options["tags"] = {
            "exclude": ["ee-bench-*", "Epic"],
            "include": ["ee-bench-codegen"],
        }
        records = list(generator.generate(provider, context))
        tags = json.loads(records[0]["tags"])
        assert tags == ["bug", "ee-bench-codegen"]

    def test_tags_backward_compat_flat_exclude(self, generator, context):
        """Old flat 'exclude' key still works when no 'tags' section."""
        provider = _make_provider(
            field_values={
                "description": "desc",
                "patch": "diff",
                "repo_url": "https://github.com/o/r.git",
                "labels": ["ee-bench-codegen", "bug"],
            },
            items=[{"owner": "o", "repo": "r", "number": 1}],
            extra_fields=[FieldDescriptor("labels", "pull_request")],
        )
        context.options["exclude"] = ["ee-bench-codegen"]
        records = list(generator.generate(provider, context))
        tags = json.loads(records[0]["tags"])
        assert tags == ["bug"]

    def test_version_from_context_options(self, generator, context):
        """When provider has no version, fall back to context options."""
        provider = _make_provider(
            field_values={
                "description": "desc",
                "patch": "diff",
                "repo_url": "https://github.com/o/r.git",
            },
            items=[{"owner": "o", "repo": "r", "number": 1}],
        )
        context.options["version"] = "42"
        records = list(generator.generate(provider, context))
        assert records[0]["version"] == "42"
