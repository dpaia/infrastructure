"""Integration tests for the DatasetEngine with real plugins.

These tests verify that the engine works correctly with the actual
provider and generator implementations.
"""

import json

import pytest
import responses

from ee_bench_generator import DatasetEngine
from ee_bench_generator.loader import load_generator, load_provider
from ee_bench_generator.matcher import validate_compatibility
from ee_bench_generator.metadata import Selection
from ee_bench_github.api import DEFAULT_BASE_URL


class TestEngineWithRealPlugins:
    """Integration tests using real provider and generator plugins."""

    @responses.activate
    def test_engine_generates_valid_records(self):
        """Test that engine produces valid records with real plugins."""
        # Mock GitHub API responses
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/apache/kafka/pulls/123",
            json={
                "number": 123,
                "title": "KAFKA-1234: Fix consumer lag calculation",
                "body": "This PR fixes the consumer lag calculation bug.\n\nFAIL_TO_PASS: [\"kafka.consumer.LagTest.testLagCalculation\"]",
                "base": {"sha": "abc123" + "0" * 34},
                "head": {"sha": "def456" + "0" * 34},
                "labels": [{"name": "bug"}, {"name": "consumer"}],
            },
            status=200,
        )
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/apache/kafka/pulls/123",
            body="diff --git a/core/src/main/java/kafka/consumer/Lag.java b/core/src/main/java/kafka/consumer/Lag.java\n@@ -10,7 +10,7 @@\n-    return offset - position;\n+    return Math.max(0, offset - position);",
            status=200,
            content_type="text/plain",
        )

        # Load plugins
        provider = load_provider("github_pull_requests")
        generator = load_generator("dpaia_jvm")

        selection = Selection(
            resource="pull_requests",
            filters={"repo": "apache/kafka", "pr_numbers": [123]},
        )

        engine = DatasetEngine(provider, generator)
        records = list(engine.run(selection, provider_options={"token": "test-token"}))

        assert len(records) == 1
        record = records[0]

        # Verify instance_id format
        assert record["instance_id"] == "apache__kafka__123"

        # Verify required fields
        assert record["repo"] == "https://github.com/apache/kafka.git"
        assert record["base_commit"] == "abc123" + "0" * 34
        assert "diff --git" in record["patch"]
        assert "Math.max" in record["patch"]

        # Verify problem statement combines title and body
        assert "KAFKA-1234" in record["problem_statement"]
        assert "consumer lag calculation" in record["problem_statement"]

        # Verify test fields
        fail_to_pass = json.loads(record["FAIL_TO_PASS"])
        assert fail_to_pass == ["kafka.consumer.LagTest.testLagCalculation"]

        # Verify timestamp
        assert "created_at" in record
        assert record["created_at"].endswith("+00:00") or record["created_at"].endswith("Z")

    @responses.activate
    def test_engine_handles_multiple_prs(self):
        """Test engine processes multiple PRs correctly."""
        # Mock multiple PRs
        for num in [1, 2, 3]:
            responses.add(
                responses.GET,
                f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/{num}",
                json={
                    "number": num,
                    "title": f"Fix issue {num}",
                    "body": f"Description for issue {num}",
                    "base": {"sha": f"{num}" * 40},
                    "head": {"sha": f"{num + 3}" * 40},
                    "labels": [],
                },
                status=200,
            )
            responses.add(
                responses.GET,
                f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/{num}",
                body=f"diff for PR {num}",
                status=200,
                content_type="text/plain",
            )

        provider = load_provider("github_pull_requests")
        generator = load_generator("dpaia_jvm")

        selection = Selection(
            resource="pull_requests",
            filters={"repo": "owner/repo", "pr_numbers": [1, 2, 3]},
        )

        engine = DatasetEngine(provider, generator)
        records = list(engine.run(selection, provider_options={"token": "test-token"}))

        assert len(records) == 3

        # Verify each record has unique instance_id
        instance_ids = [r["instance_id"] for r in records]
        assert instance_ids == ["owner__repo__1", "owner__repo__2", "owner__repo__3"]

        # Verify each record has correct base_commit
        for i, record in enumerate(records, 1):
            assert record["base_commit"] == f"{i}" * 40

    @responses.activate
    def test_engine_with_empty_test_fields(self):
        """Test engine handles PRs without FAIL_TO_PASS/PASS_TO_PASS markers."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/1",
            json={
                "number": 1,
                "title": "Simple fix",
                "body": "Just a simple fix without test markers.",
                "base": {"sha": "a" * 40},
                "head": {"sha": "b" * 40},
                "labels": [],
            },
            status=200,
        )
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/1",
            body="diff content",
            status=200,
            content_type="text/plain",
        )

        provider = load_provider("github_pull_requests")
        generator = load_generator("dpaia_jvm")

        selection = Selection(
            resource="pull_requests",
            filters={"repo": "owner/repo", "pr_numbers": [1]},
        )

        engine = DatasetEngine(provider, generator)
        records = list(engine.run(selection, provider_options={"token": "test-token"}))

        assert len(records) == 1
        record = records[0]

        # Test fields should default to empty arrays
        assert record["FAIL_TO_PASS"] == "[]"
        assert record["PASS_TO_PASS"] == "[]"


class TestPluginLoading:
    """Tests for plugin discovery and loading."""

    def test_load_github_pull_requests_provider(self):
        """Test loading the GitHub pull requests provider."""
        provider = load_provider("github_pull_requests")

        assert provider is not None
        assert provider.metadata.name == "github_pull_requests"
        assert "pull_request" in provider.metadata.sources

    def test_load_github_issues_provider(self):
        """Test loading the GitHub issues provider."""
        provider = load_provider("github_issues")

        assert provider is not None
        assert provider.metadata.name == "github_issues"
        assert "issue" in provider.metadata.sources

    def test_load_dpaia_jvm_generator(self):
        """Test loading the DPAIA JVM generator."""
        generator = load_generator("dpaia_jvm")

        assert generator is not None
        assert generator.metadata.name == "dpaia_jvm"

        # Check required fields
        required_names = {f.name for f in generator.metadata.required_fields}
        assert "description" in required_names
        assert "base_commit" in required_names
        assert "patch" in required_names
        assert "repo_url" in required_names


class TestCompatibilityMatrix:
    """Tests verifying compatibility between providers and generators."""

    def test_github_pull_requests_compatible_with_dpaia_jvm(self):
        """Test that github_pull_requests is compatible with dpaia_jvm."""
        provider = load_provider("github_pull_requests")
        generator = load_generator("dpaia_jvm")

        result = validate_compatibility(provider.metadata, generator.metadata)

        assert result.compatible is True
        assert len(result.missing_required) == 0

    def test_github_issues_incompatible_with_dpaia_jvm(self):
        """Test that github_issues is NOT compatible with dpaia_jvm."""
        provider = load_provider("github_issues")
        generator = load_generator("dpaia_jvm")

        result = validate_compatibility(provider.metadata, generator.metadata)

        assert result.compatible is False

        # Should be missing base_commit, patch (issue provider doesn't have these)
        missing_names = {f.name for f in result.missing_required}
        assert "base_commit" in missing_names
        assert "patch" in missing_names
