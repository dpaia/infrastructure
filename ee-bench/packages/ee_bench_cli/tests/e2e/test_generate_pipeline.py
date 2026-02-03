"""End-to-end tests for the generate pipeline.

These tests verify the full pipeline from CLI through provider to generator,
using mocked HTTP responses for GitHub API calls.
"""

import json
import os
import tempfile

import pytest
import responses
from click.testing import CliRunner

from ee_bench_cli.cli import cli
from ee_bench_github.api import DEFAULT_BASE_URL


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def github_token(monkeypatch):
    """Set up GitHub token for tests."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")


class TestGeneratePipelineE2E:
    """End-to-end tests for the generate command."""

    @responses.activate
    def test_generate_single_pr_to_file(self, runner, github_token):
        """Test generating a single PR record to a file."""
        # Mock PR endpoint (for JSON data)
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/42",
            json={
                "number": 42,
                "title": "Fix NPE in Parser",
                "body": "This PR fixes a null pointer exception.\n\nFAIL_TO_PASS: [\"test.ParserTest.testNull\"]",
                "base": {"sha": "a" * 40},
                "head": {"sha": "b" * 40},
                "labels": [{"name": "bug"}],
            },
            status=200,
        )

        # Mock diff endpoint
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/42",
            body="diff --git a/Parser.java b/Parser.java\n+fix null check",
            status=200,
            content_type="text/plain",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "output.jsonl")

            result = runner.invoke(
                cli,
                [
                    "generate",
                    "--provider", "github_pull_requests",
                    "--generator", "dpaia_jvm",
                    "--selection", '{"resource": "pull_requests", "filters": {"repo": "owner/repo", "pr_numbers": [42]}}',
                    "--out", output_file,
                ],
            )

            assert result.exit_code == 0, f"Command failed: {result.output}"

            # Read and parse output file
            with open(output_file) as f:
                record = json.loads(f.readline().strip())

            assert record["instance_id"] == "owner__repo__42"
            assert record["repo"] == "https://github.com/owner/repo.git"
            assert record["base_commit"] == "a" * 40
            assert "diff --git" in record["patch"]
            assert "Fix NPE in Parser" in record["problem_statement"]
            assert record["FAIL_TO_PASS"] == '["test.ParserTest.testNull"]'

    @responses.activate
    def test_generate_multiple_prs_to_jsonl(self, runner, github_token):
        """Test generating multiple records to a JSONL file."""
        # Mock PR list endpoint
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls",
            json=[
                {"number": 1, "labels": []},
                {"number": 2, "labels": []},
            ],
            status=200,
        )

        # Mock individual PR endpoints
        for num in [1, 2]:
            responses.add(
                responses.GET,
                f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/{num}",
                json={
                    "number": num,
                    "title": f"PR {num}",
                    "body": f"Description for PR {num}",
                    "base": {"sha": "a" * 40},
                    "head": {"sha": "b" * 40},
                    "labels": [],
                },
                status=200,
            )
            # Mock diff endpoint
            responses.add(
                responses.GET,
                f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/{num}",
                body=f"diff for PR {num}",
                status=200,
                content_type="text/plain",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "output.jsonl")

            result = runner.invoke(
                cli,
                [
                    "generate",
                    "--provider", "github_pull_requests",
                    "--generator", "dpaia_jvm",
                    "--selection", '{"resource": "pull_requests", "filters": {"repo": "owner/repo"}, "limit": 2}',
                    "--out", output_file,
                    "--format", "jsonl",
                ],
            )

            assert result.exit_code == 0, f"Command failed: {result.output}"

            # Read and verify output file
            with open(output_file) as f:
                lines = f.readlines()

            assert len(lines) == 2

            record1 = json.loads(lines[0])
            record2 = json.loads(lines[1])

            assert record1["instance_id"] == "owner__repo__1"
            assert record2["instance_id"] == "owner__repo__2"

    @responses.activate
    def test_generate_to_json_array_file(self, runner, github_token):
        """Test generating records to a JSON array file."""
        # Mock PR endpoint
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/1",
            json={
                "number": 1,
                "title": "PR 1",
                "body": "Description",
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

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "output.json")

            result = runner.invoke(
                cli,
                [
                    "generate",
                    "--provider", "github_pull_requests",
                    "--generator", "dpaia_jvm",
                    "--selection", '{"resource": "pull_requests", "filters": {"repo": "owner/repo", "pr_numbers": [1]}}',
                    "--out", output_file,
                    "--format", "json",
                ],
            )

            assert result.exit_code == 0, f"Command failed: {result.output}"

            # Read and verify output file
            with open(output_file) as f:
                records = json.load(f)

            assert isinstance(records, list)
            assert len(records) == 1
            assert records[0]["instance_id"] == "owner__repo__1"

    @responses.activate
    def test_generate_with_provider_options(self, runner, monkeypatch):
        """Test generating with provider options passed via CLI."""
        # Don't set GITHUB_TOKEN env var - pass via option instead
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        # Mock PR endpoint
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/1",
            json={
                "number": 1,
                "title": "PR 1",
                "body": "Description",
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

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "output.jsonl")

            result = runner.invoke(
                cli,
                [
                    "generate",
                    "--provider", "github_pull_requests",
                    "--generator", "dpaia_jvm",
                    "--selection", '{"resource": "pull_requests", "filters": {"repo": "owner/repo", "pr_numbers": [1]}}',
                    "--out", output_file,
                    "--provider-option", "token=test-token-from-cli",
                ],
            )

            assert result.exit_code == 0, f"Command failed: {result.output}"


class TestGenerateErrorHandling:
    """Tests for error handling in the generate pipeline."""

    def test_incompatible_provider_generator(self, runner, github_token):
        """Test error when provider and generator are incompatible."""
        # github_issues doesn't provide base_commit, patch which dpaia_jvm requires
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "output.jsonl")

            result = runner.invoke(
                cli,
                [
                    "generate",
                    "--provider", "github_issues",
                    "--generator", "dpaia_jvm",
                    "--selection", '{"resource": "issues", "filters": {"repo": "owner/repo"}}',
                    "--out", output_file,
                ],
            )

            assert result.exit_code != 0
            assert "incompatible" in result.output.lower() or "missing" in result.output.lower()

    @responses.activate
    def test_missing_required_selection(self, runner, github_token):
        """Test error when selection is missing required filters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "output.jsonl")

            result = runner.invoke(
                cli,
                [
                    "generate",
                    "--provider", "github_pull_requests",
                    "--generator", "dpaia_jvm",
                    "--selection", '{"resource": "pull_requests", "filters": {}}',
                    "--out", output_file,
                ],
            )

            # Should fail because repo is required
            assert result.exit_code != 0

    def test_invalid_json_selection(self, runner, github_token):
        """Test error with invalid JSON in selection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "output.jsonl")

            result = runner.invoke(
                cli,
                [
                    "generate",
                    "--provider", "github_pull_requests",
                    "--generator", "dpaia_jvm",
                    "--selection", "not valid json",
                    "--out", output_file,
                ],
            )

            assert result.exit_code != 0
            assert "json" in result.output.lower() or "invalid" in result.output.lower()

    def test_nonexistent_provider(self, runner):
        """Test error with nonexistent provider."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "output.jsonl")

            result = runner.invoke(
                cli,
                [
                    "generate",
                    "--provider", "nonexistent_provider",
                    "--generator", "dpaia_jvm",
                    "--selection", '{"resource": "test", "filters": {}}',
                    "--out", output_file,
                ],
            )

            assert result.exit_code != 0
            assert "not found" in result.output.lower()

    def test_nonexistent_generator(self, runner, github_token):
        """Test error with nonexistent generator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "output.jsonl")

            result = runner.invoke(
                cli,
                [
                    "generate",
                    "--provider", "github_pull_requests",
                    "--generator", "nonexistent_generator",
                    "--selection", '{"resource": "test", "filters": {}}',
                    "--out", output_file,
                ],
            )

            assert result.exit_code != 0
            assert "not found" in result.output.lower()
