"""Tests for GitHub Issues provider."""

import pytest
import responses

from ee_bench_generator.metadata import Context, Selection

from ee_bench_github import GitHubIssuesProvider
from ee_bench_github.api import DEFAULT_BASE_URL


@pytest.fixture
def provider():
    """Create a test provider."""
    p = GitHubIssuesProvider()
    p.prepare(token="test-token")
    return p


@pytest.fixture
def context():
    """Create a test context."""
    return Context(
        selection=Selection(
            resource="issues",
            filters={"repo": "owner/repo", "issue_numbers": [42]},
        ),
        current_item={"owner": "owner", "repo": "repo", "number": 42},
    )


class TestGitHubIssuesProviderMetadata:
    """Tests for provider metadata."""

    def test_metadata_name(self):
        """Test provider name."""
        provider = GitHubIssuesProvider()
        assert provider.metadata.name == "github_issues"

    def test_metadata_sources(self):
        """Test provider sources."""
        provider = GitHubIssuesProvider()
        assert "issue" in provider.metadata.sources
        assert "repository" in provider.metadata.sources

    def test_metadata_provided_fields(self):
        """Test provider declares required fields."""
        provider = GitHubIssuesProvider()
        field_names = {f.name for f in provider.metadata.provided_fields}

        assert "description" in field_names
        assert "title" in field_names
        assert "labels" in field_names
        assert "repo_tree" in field_names
        assert "repo_url" in field_names


class TestGitHubIssuesProviderPrepare:
    """Tests for prepare method."""

    def test_prepare_creates_client(self):
        """Test that prepare creates API client."""
        provider = GitHubIssuesProvider()
        provider.prepare(token="my-token")

        assert provider._client is not None
        assert provider._client.token == "my-token"

    def test_prepare_with_custom_options(self):
        """Test prepare with custom options."""
        provider = GitHubIssuesProvider()
        provider.prepare(
            token="my-token",
            base_url="https://custom.api.com",
            timeout=60,
        )

        assert provider._client.base_url == "https://custom.api.com"
        assert provider._client.timeout == 60


class TestGitHubIssuesProviderGetField:
    """Tests for get_field method."""

    @responses.activate
    def test_get_description(self, provider, context):
        """Test getting issue description."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/issues/42",
            json={"body": "Issue description text", "title": "Bug report"},
            status=200,
        )

        result = provider.get_field("description", "issue", context)

        assert result == "Issue description text"

    @responses.activate
    def test_get_title(self, provider, context):
        """Test getting issue title."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/issues/42",
            json={"body": "Description", "title": "Bug report"},
            status=200,
        )

        result = provider.get_field("title", "issue", context)

        assert result == "Bug report"

    @responses.activate
    def test_get_labels(self, provider, context):
        """Test getting issue labels."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/issues/42",
            json={
                "body": "Description",
                "labels": [{"name": "bug"}, {"name": "priority"}],
            },
            status=200,
        )

        result = provider.get_field("labels", "issue", context)

        assert result == ["bug", "priority"]

    @responses.activate
    def test_get_repo_url(self, provider, context):
        """Test getting repository URL."""
        result = provider.get_field("repo_url", "repository", context)

        assert result == "https://github.com/owner/repo.git"

    @responses.activate
    def test_get_repo_tree(self, provider, context):
        """Test getting repository tree."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/git/trees/HEAD",
            json={
                "tree": [
                    {"path": "src/main.py", "type": "blob"},
                    {"path": "src/utils.py", "type": "blob"},
                    {"path": "src", "type": "tree"},
                ]
            },
            status=200,
        )

        result = provider.get_field("repo_tree", "repository", context)

        # Should only include blobs (files), not trees (directories)
        assert "src/main.py" in result
        assert "src/utils.py" in result
        assert "src" not in result

    def test_get_field_without_prepare_raises(self):
        """Test that get_field without prepare raises error."""
        provider = GitHubIssuesProvider()
        context = Context(
            selection=Selection(resource="issues", filters={}),
            current_item={"owner": "o", "repo": "r", "number": 1},
        )

        with pytest.raises(Exception, match="not prepared"):
            provider.get_field("description", "issue", context)


class TestGitHubIssuesProviderIterItems:
    """Tests for iter_items method."""

    @responses.activate
    def test_iter_specific_issues(self, provider):
        """Test iterating over specific issue numbers."""
        context = Context(
            selection=Selection(
                resource="issues",
                filters={"repo": "owner/repo", "issue_numbers": [1, 2, 3]},
            )
        )

        items = list(provider.iter_items(context))

        assert len(items) == 3
        assert items[0] == {"owner": "owner", "repo": "repo", "number": 1}
        assert items[1] == {"owner": "owner", "repo": "repo", "number": 2}
        assert items[2] == {"owner": "owner", "repo": "repo", "number": 3}

    @responses.activate
    def test_iter_all_issues(self, provider):
        """Test iterating over all issues."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/issues",
            json=[
                {"number": 10, "title": "Issue 10"},
                {"number": 11, "title": "Issue 11"},
            ],
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="issues",
                filters={"repo": "owner/repo"},
            )
        )

        items = list(provider.iter_items(context))

        assert len(items) == 2
        assert items[0]["number"] == 10
        assert items[1]["number"] == 11

    @responses.activate
    def test_iter_skips_pull_requests(self, provider):
        """Test that PRs are skipped when listing issues."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/issues",
            json=[
                {"number": 10, "title": "Issue"},
                {"number": 11, "title": "PR", "pull_request": {"url": "..."}},
            ],
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="issues",
                filters={"repo": "owner/repo"},
            )
        )

        items = list(provider.iter_items(context))

        assert len(items) == 1
        assert items[0]["number"] == 10

    @responses.activate
    def test_iter_with_limit(self, provider):
        """Test iterating with limit."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/issues",
            json=[
                {"number": i}
                for i in range(10)
            ],
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="issues",
                filters={"repo": "owner/repo"},
                limit=3,
            )
        )

        items = list(provider.iter_items(context))

        assert len(items) == 3

    def test_iter_without_repo_raises(self, provider):
        """Test that missing repo filter raises error."""
        context = Context(
            selection=Selection(
                resource="issues",
                filters={},
            )
        )

        with pytest.raises(Exception, match="repo"):
            list(provider.iter_items(context))
