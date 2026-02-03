"""Tests for GitHub API client."""

import pytest
import responses

from ee_bench_github.api import (
    DEFAULT_BASE_URL,
    GitHubAPIClient,
    GitHubAPIError,
    RateLimitError,
)


@pytest.fixture
def client():
    """Create a test client."""
    return GitHubAPIClient(token="test-token")


class TestGitHubAPIClient:
    """Tests for GitHubAPIClient class."""

    def test_init_with_token(self):
        """Test initialization with explicit token."""
        client = GitHubAPIClient(token="my-token")

        assert client.token == "my-token"
        assert "Authorization" in client.session.headers

    def test_init_without_token(self, monkeypatch):
        """Test initialization without token uses env var."""
        monkeypatch.setenv("GITHUB_TOKEN", "env-token")
        client = GitHubAPIClient()

        assert client.token == "env-token"

    def test_init_custom_base_url(self):
        """Test initialization with custom base URL."""
        client = GitHubAPIClient(base_url="https://github.example.com/api/v3")

        assert client.base_url == "https://github.example.com/api/v3"

    def test_headers_set_correctly(self, client):
        """Test that headers are set correctly."""
        headers = client.session.headers

        assert headers["Accept"] == "application/vnd.github.v3+json"
        assert headers["User-Agent"] == "ee-bench/0.1"
        assert "token test-token" in headers["Authorization"]

    @responses.activate
    def test_get_success(self, client):
        """Test successful GET request."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo",
            json={"name": "repo", "full_name": "owner/repo"},
            status=200,
        )

        result = client.get("/repos/owner/repo")

        assert result["name"] == "repo"
        assert result["full_name"] == "owner/repo"

    @responses.activate
    def test_get_with_params(self, client):
        """Test GET request with query parameters."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/issues",
            json=[{"number": 1}],
            status=200,
        )

        result = client.get("/repos/owner/repo/issues", state="open", per_page=10)

        assert len(responses.calls) == 1
        assert "state=open" in responses.calls[0].request.url
        assert "per_page=10" in responses.calls[0].request.url

    @responses.activate
    def test_get_404_raises_error(self, client):
        """Test that 404 raises GitHubAPIError."""
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/nonexistent",
            json={"message": "Not Found"},
            status=404,
        )

        with pytest.raises(GitHubAPIError) as exc_info:
            client.get("/repos/owner/nonexistent")

        assert exc_info.value.status_code == 404
        assert "Not Found" in exc_info.value.message

    @responses.activate
    def test_rate_limit_retry(self, client):
        """Test that rate limiting triggers retry."""
        import time

        # First request - rate limited
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/test",
            json={"message": "rate limit exceeded"},
            status=403,
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + 1),
            },
        )
        # Second request - success
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/test",
            json={"success": True},
            status=200,
        )

        result = client.get("/test")

        assert result["success"] is True
        assert len(responses.calls) == 2

    @responses.activate
    def test_server_error_retry(self, client):
        """Test that 5xx errors trigger retry."""
        # First two requests - server error
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/test",
            json={"error": "Internal Server Error"},
            status=500,
        )
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/test",
            json={"error": "Internal Server Error"},
            status=500,
        )
        # Third request - success
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/test",
            json={"success": True},
            status=200,
        )

        # Use client with short backoff for testing
        client = GitHubAPIClient(token="test", max_retries=3)
        result = client.get("/test")

        assert result["success"] is True

    @responses.activate
    def test_get_paginated(self, client):
        """Test paginated GET request."""
        # First page
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/issues",
            json=[{"number": 1}, {"number": 2}],
            status=200,
            headers={
                "Link": f'<{DEFAULT_BASE_URL}/repos/owner/repo/issues?page=2>; rel="next"'
            },
        )
        # Second page
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/issues?page=2",
            json=[{"number": 3}],
            status=200,
        )

        results = list(client.get_paginated("/repos/owner/repo/issues"))

        assert len(results) == 3
        assert [r["number"] for r in results] == [1, 2, 3]

    @responses.activate
    def test_get_diff(self, client):
        """Test getting diff content."""
        diff_content = "diff --git a/file.py b/file.py\n+added line"
        responses.add(
            responses.GET,
            f"{DEFAULT_BASE_URL}/repos/owner/repo/pulls/1",
            body=diff_content,
            status=200,
            content_type="text/plain",
        )

        result = client.get_diff("/repos/owner/repo/pulls/1")

        assert result == diff_content
        # Check that diff Accept header was used
        assert "application/vnd.github.v3.diff" in responses.calls[0].request.headers["Accept"]


class TestGitHubAPIError:
    """Tests for GitHubAPIError exception."""

    def test_error_message(self):
        """Test error message format."""
        error = GitHubAPIError(404, "Not Found")

        assert error.status_code == 404
        assert error.message == "Not Found"
        assert "404" in str(error)
        assert "Not Found" in str(error)


class TestRateLimitError:
    """Tests for RateLimitError exception."""

    def test_error_with_reset_time(self):
        """Test error with reset time."""
        error = RateLimitError(reset_time=1234567890)

        assert error.reset_time == 1234567890
        assert "1234567890" in str(error)
