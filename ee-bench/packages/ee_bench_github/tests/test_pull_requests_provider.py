"""Tests for GitHub Pull Requests provider."""

import pytest
import responses

from ee_bench_generator.metadata import Context, Selection

from ee_bench_github import GitHubPullRequestsProvider
from ee_bench_github.api import DEFAULT_BASE_URL


@pytest.fixture
def provider():
    """Create a test provider."""
    p = GitHubPullRequestsProvider()
    p.prepare(token="test-token")
    return p


@pytest.fixture
def context():
    """Create a test context."""
    return Context(
        selection=Selection(
            resource="pull_requests",
            filters={"repo": "owner/repo", "pr_numbers": [42]},
        ),
        current_item={"owner": "owner", "repo": "repo", "number": 42},
    )


class TestGitHubPullRequestsProviderMetadata:
    """Tests for provider metadata."""

    def test_metadata_name(self):
        """Test provider name."""
        provider = GitHubPullRequestsProvider()
        assert provider.metadata.name == "github_pull_requests"

    def test_metadata_sources(self):
        """Test provider sources."""
        provider = GitHubPullRequestsProvider()
        assert "pull_request" in provider.metadata.sources
        assert "repository" in provider.metadata.sources

    def test_metadata_provided_fields(self):
        """Test provider declares all required fields."""
        provider = GitHubPullRequestsProvider()
        field_names = {f.name for f in provider.metadata.provided_fields}

        # Core fields
        assert "description" in field_names
        assert "title" in field_names
        assert "labels" in field_names

        # PR-specific fields
        assert "base_commit" in field_names
        assert "head_commit" in field_names
        assert "commits" in field_names
        assert "patch" in field_names

        # Test fields
        assert "FAIL_TO_PASS" in field_names
        assert "PASS_TO_PASS" in field_names

        # Repository fields
        assert "repo_tree" in field_names
        assert "repo_url" in field_names


class TestGitHubPullRequestsProviderGetField:
    """Tests for get_field method."""

    @responses.activate
    def test_get_description(self, provider, context):
        """Test getting PR description."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/42",
            json={
                "body": "PR description",
                "title": "Fix bug",
                "base": {"sha": "abc123"},
                "head": {"sha": "def456"},
            },
            status=200,
        )

        result = provider.get_field("description", "pull_request", context)

        assert result == "PR description"

    @responses.activate
    def test_get_base_commit(self, provider, context):
        """Test getting base commit SHA."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/42",
            json={
                "body": "",
                "base": {"sha": "abc123"},
                "head": {"sha": "def456"},
            },
            status=200,
        )

        result = provider.get_field("base_commit", "pull_request", context)

        assert result == "abc123"

    @responses.activate
    def test_get_commits(self, provider, context):
        """Test getting PR commits."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/42",
            json={
                "body": "",
                "base": {"sha": "abc123"},
                "head": {"sha": "def456"},
            },
            status=200,
        )
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/42/commits",
            json=[
                {"sha": "commit1"},
                {"sha": "commit2"},
            ],
            status=200,
        )

        result = provider.get_field("commits", "pull_request", context)

        assert result == ["commit1", "commit2"]

    @responses.activate
    def test_get_patch(self, provider, context):
        """Test getting PR diff."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/42",
            body="diff --git a/file.py b/file.py\n+new line",
            status=200,
        )

        result = provider.get_field("patch", "pull_request", context)

        assert "diff --git" in result
        assert "+new line" in result

    @responses.activate
    def test_get_fail_to_pass(self, provider, context):
        """Test getting FAIL_TO_PASS from PR body."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/42",
            json={
                "body": 'FAIL_TO_PASS: ["test1", "test2"]',
                "base": {"sha": "abc"},
                "head": {"sha": "def"},
            },
            status=200,
        )

        result = provider.get_field("FAIL_TO_PASS", "pull_request", context)

        assert result == '["test1", "test2"]'

    @responses.activate
    def test_get_pass_to_pass(self, provider, context):
        """Test getting PASS_TO_PASS from PR body."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/42",
            json={
                "body": 'PASS_TO_PASS: ["test3"]',
                "base": {"sha": "abc"},
                "head": {"sha": "def"},
            },
            status=200,
        )

        result = provider.get_field("PASS_TO_PASS", "pull_request", context)

        assert result == '["test3"]'

    @responses.activate
    def test_get_repo_tree_at_base(self, provider, context):
        """Test getting repo tree at base commit."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/42",
            json={
                "body": "",
                "base": {"sha": "abc123"},
                "head": {"sha": "def456"},
            },
            status=200,
        )
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/git/trees/abc123",
            json={
                "tree": [
                    {"path": "src/main.py", "type": "blob"},
                    {"path": "tests/test_main.py", "type": "blob"},
                ]
            },
            status=200,
        )

        result = provider.get_field("repo_tree", "repository", context)

        assert "src/main.py" in result
        assert "tests/test_main.py" in result

    @responses.activate
    def test_get_repo_url(self, provider, context):
        """Test getting repository URL."""
        result = provider.get_field("repo_url", "repository", context)

        assert result == "https://github.com/owner/repo.git"

    @responses.activate
    def test_get_labels(self, provider, context):
        """Test getting PR labels."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/42",
            json={
                "body": "",
                "base": {"sha": "abc"},
                "head": {"sha": "def"},
                "labels": [{"name": "bug"}, {"name": "verified"}],
            },
            status=200,
        )

        result = provider.get_field("labels", "pull_request", context)

        assert result == ["bug", "verified"]


class TestGitHubPullRequestsProviderIterItems:
    """Tests for iter_items method."""

    @responses.activate
    def test_iter_specific_prs(self, provider):
        """Test iterating over specific PR numbers."""
        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={"repo": "owner/repo", "pr_numbers": [1, 2, 3]},
            )
        )

        items = list(provider.iter_items(context))

        assert len(items) == 3
        assert items[0] == {"owner": "owner", "repo": "repo", "number": 1}
        assert items[1] == {"owner": "owner", "repo": "repo", "number": 2}
        assert items[2] == {"owner": "owner", "repo": "repo", "number": 3}

    @responses.activate
    def test_iter_all_prs(self, provider):
        """Test iterating over all PRs."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls",
            json=[
                {"number": 10, "title": "PR 10", "labels": []},
                {"number": 11, "title": "PR 11", "labels": []},
            ],
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={"repo": "owner/repo"},
            )
        )

        items = list(provider.iter_items(context))

        assert len(items) == 2
        assert items[0]["number"] == 10
        assert items[1]["number"] == 11

    @responses.activate
    def test_iter_with_label_filter(self, provider):
        """Test filtering PRs by label."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls",
            json=[
                {"number": 10, "labels": [{"name": "bug"}]},
                {"number": 11, "labels": [{"name": "feature"}]},
                {"number": 12, "labels": [{"name": "bug"}, {"name": "verified"}]},
            ],
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={"repo": "owner/repo", "labels": ["bug"]},
            )
        )

        items = list(provider.iter_items(context))

        # Should only include PRs with "bug" label
        assert len(items) == 2
        assert items[0]["number"] == 10
        assert items[1]["number"] == 12

    @responses.activate
    def test_iter_with_limit(self, provider):
        """Test iterating with limit."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls",
            json=[{"number": i, "labels": []} for i in range(10)],
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
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
                resource="pull_requests",
                filters={},
            )
        )

        with pytest.raises(Exception, match="repo"):
            list(provider.iter_items(context))


class TestGitHubPullRequestsProviderSearchQuery:
    """Tests for GitHub Search Query support."""

    @responses.activate
    def test_iter_with_search_query(self, provider):
        """Test iterating with search query."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/search/issues",
            json={
                "items": [
                    {
                        "number": 1,
                        "repository_url": "https://api.github.com/repos/apache/kafka",
                        "pull_request": {"url": "..."},
                    },
                    {
                        "number": 2,
                        "repository_url": "https://api.github.com/repos/apache/kafka",
                        "pull_request": {"url": "..."},
                    },
                ]
            },
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={"query": "is:pr is:merged label:bug repo:apache/kafka"},
            )
        )

        items = list(provider.iter_items(context))

        assert len(items) == 2
        assert items[0] == {"owner": "apache", "repo": "kafka", "number": 1}
        assert items[1] == {"owner": "apache", "repo": "kafka", "number": 2}

        # Verify query was passed correctly
        assert "q=" in responses.calls[0].request.url
        assert "is%3Apr" in responses.calls[0].request.url  # URL encoded

    @responses.activate
    def test_iter_search_skips_non_prs(self, provider):
        """Test that search results skip non-PR items (issues)."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/search/issues",
            json={
                "items": [
                    {
                        "number": 1,
                        "repository_url": "https://api.github.com/repos/apache/kafka",
                        "pull_request": {"url": "..."},  # This is a PR
                    },
                    {
                        "number": 2,
                        "repository_url": "https://api.github.com/repos/apache/kafka",
                        # No "pull_request" key - this is an issue
                    },
                ]
            },
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={"query": "repo:apache/kafka"},
            )
        )

        items = list(provider.iter_items(context))

        # Should only include the PR, not the issue
        assert len(items) == 1
        assert items[0]["number"] == 1

    @responses.activate
    def test_iter_search_with_limit(self, provider):
        """Test search query respects limit."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/search/issues",
            json={
                "items": [
                    {
                        "number": i,
                        "repository_url": "https://api.github.com/repos/apache/kafka",
                        "pull_request": {"url": "..."},
                    }
                    for i in range(10)
                ]
            },
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={"query": "is:pr repo:apache/kafka"},
                limit=3,
            )
        )

        items = list(provider.iter_items(context))

        assert len(items) == 3

    def test_search_query_mutually_exclusive_with_repo(self, provider):
        """Test that query and repo cannot be used together."""
        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={
                    "query": "is:pr",
                    "repo": "apache/kafka",
                },
            )
        )

        with pytest.raises(Exception, match="Cannot use 'query' filter together"):
            list(provider.iter_items(context))

    def test_search_query_mutually_exclusive_with_repos(self, provider):
        """Test that query and repos cannot be used together."""
        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={
                    "query": "is:pr",
                    "repos": ["apache/kafka"],
                },
            )
        )

        with pytest.raises(Exception, match="Cannot use 'query' filter together"):
            list(provider.iter_items(context))

    @responses.activate
    def test_iter_search_multiple_repos_in_results(self, provider):
        """Test search results can span multiple repositories."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/search/issues",
            json={
                "items": [
                    {
                        "number": 1,
                        "repository_url": "https://api.github.com/repos/apache/kafka",
                        "pull_request": {"url": "..."},
                    },
                    {
                        "number": 2,
                        "repository_url": "https://api.github.com/repos/apache/flink",
                        "pull_request": {"url": "..."},
                    },
                ]
            },
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={"query": "is:pr org:apache label:bug"},
            )
        )

        items = list(provider.iter_items(context))

        assert len(items) == 2
        repos = {item["repo"] for item in items}
        assert repos == {"kafka", "flink"}


class TestGitHubPullRequestsProviderWildcard:
    """Tests for wildcard pattern support."""

    @responses.activate
    def test_iter_with_wildcard_pattern(self, provider):
        """Test iterating with wildcard pattern."""
        # Mock org repos endpoint
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/orgs/apache/repos",
            json=[{"name": "kafka"}, {"name": "kafka-clients"}, {"name": "flink"}],
            status=200,
        )
        # Mock PRs for matched repos
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/apache/kafka/pulls",
            json=[{"number": 1, "labels": []}],
            status=200,
        )
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/apache/kafka-clients/pulls",
            json=[{"number": 2, "labels": []}],
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={"repo": "apache/kafka*"},
            )
        )

        items = list(provider.iter_items(context))

        # Should get PRs from kafka and kafka-clients (not flink)
        assert len(items) == 2
        repo_names = {item["repo"] for item in items}
        assert repo_names == {"kafka", "kafka-clients"}

    @responses.activate
    def test_iter_wildcard_all_repos(self, provider):
        """Test iterating with * pattern (all repos in org)."""
        # Mock org repos endpoint
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/orgs/apache/repos",
            json=[{"name": "kafka"}, {"name": "flink"}],
            status=200,
        )
        # Mock PRs for repos
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/apache/kafka/pulls",
            json=[{"number": 1, "labels": []}],
            status=200,
        )
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/apache/flink/pulls",
            json=[{"number": 2, "labels": []}],
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={"repo": "apache/*"},
            )
        )

        items = list(provider.iter_items(context))

        assert len(items) == 2
        repo_names = {item["repo"] for item in items}
        assert repo_names == {"kafka", "flink"}

    @responses.activate
    def test_iter_wildcard_user_repos(self, provider):
        """Test wildcard pattern falls back to user repos if org not found."""
        # Mock org repos 404
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/orgs/myuser/repos",
            json={"message": "Not Found"},
            status=404,
        )
        # Mock user repos endpoint
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/users/myuser/repos",
            json=[{"name": "project1"}, {"name": "project2"}],
            status=200,
        )
        # Mock PRs for repos
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/myuser/project1/pulls",
            json=[{"number": 1, "labels": []}],
            status=200,
        )
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/myuser/project2/pulls",
            json=[{"number": 2, "labels": []}],
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={"repo": "myuser/*"},
            )
        )

        items = list(provider.iter_items(context))

        assert len(items) == 2

    @responses.activate
    def test_iter_mixed_patterns_and_explicit(self, provider):
        """Test mixing wildcard patterns and explicit repos."""
        # Mock org repos endpoint
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/orgs/apache/repos",
            json=[{"name": "kafka"}, {"name": "flink"}],
            status=200,
        )
        # Mock PRs for all repos
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/apache/kafka/pulls",
            json=[{"number": 1, "labels": []}],
            status=200,
        )
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/apache/flink/pulls",
            json=[{"number": 2, "labels": []}],
            status=200,
        )
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/other/repo/pulls",
            json=[{"number": 3, "labels": []}],
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={
                    "repos": ["apache/*", "other/repo"],  # Pattern + explicit
                },
            )
        )

        items = list(provider.iter_items(context))

        assert len(items) == 3


class TestGitHubPullRequestsProviderMultiRepo:
    """Tests for multiple repository support."""

    @responses.activate
    def test_iter_multiple_repos(self, provider):
        """Test iterating over multiple repositories."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo1/pulls",
            json=[{"number": 1, "labels": []}, {"number": 2, "labels": []}],
            status=200,
        )
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo2/pulls",
            json=[{"number": 10, "labels": []}, {"number": 11, "labels": []}],
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={"repos": ["owner/repo1", "owner/repo2"]},
            )
        )

        items = list(provider.iter_items(context))

        assert len(items) == 4
        # Items from repo1
        assert {"owner": "owner", "repo": "repo1", "number": 1} in items
        assert {"owner": "owner", "repo": "repo1", "number": 2} in items
        # Items from repo2
        assert {"owner": "owner", "repo": "repo2", "number": 10} in items
        assert {"owner": "owner", "repo": "repo2", "number": 11} in items

    @responses.activate
    def test_iter_multiple_repos_with_limit(self, provider):
        """Test iterating over multiple repos with global limit."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo1/pulls",
            json=[{"number": i, "labels": []} for i in range(1, 6)],
            status=200,
        )
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo2/pulls",
            json=[{"number": i, "labels": []} for i in range(10, 16)],
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={"repos": ["owner/repo1", "owner/repo2"]},
                limit=3,
            )
        )

        items = list(provider.iter_items(context))

        # Limit applies globally across all repos
        assert len(items) == 3

    @responses.activate
    def test_iter_repos_single_string(self, provider):
        """Test 'repos' filter with a single string value."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo1/pulls",
            json=[{"number": 1, "labels": []}],
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={"repos": "owner/repo1"},  # Single string, not list
            )
        )

        items = list(provider.iter_items(context))

        assert len(items) == 1
        assert items[0] == {"owner": "owner", "repo": "repo1", "number": 1}

    @responses.activate
    def test_iter_both_repo_and_repos(self, provider):
        """Test using both 'repo' and 'repos' together."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo1/pulls",
            json=[{"number": 1, "labels": []}],
            status=200,
        )
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo2/pulls",
            json=[{"number": 2, "labels": []}],
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={
                    "repos": ["owner/repo1"],
                    "repo": "owner/repo2",  # Also specified
                },
            )
        )

        items = list(provider.iter_items(context))

        # Both repos should be included
        assert len(items) == 2

    @responses.activate
    def test_iter_multiple_repos_with_state_filter(self, provider):
        """Test multiple repos with state filter."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo1/pulls",
            json=[{"number": 1, "labels": []}],
            status=200,
        )
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo2/pulls",
            json=[{"number": 2, "labels": []}],
            status=200,
        )

        context = Context(
            selection=Selection(
                resource="pull_requests",
                filters={"repos": ["owner/repo1", "owner/repo2"], "state": "closed"},
            )
        )

        items = list(provider.iter_items(context))

        # Verify state param was passed in requests
        for call in responses.calls:
            assert "state=closed" in call.request.url

        assert len(items) == 2
