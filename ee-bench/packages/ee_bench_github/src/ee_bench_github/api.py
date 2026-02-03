"""GitHub API client with authentication, rate limiting, and retries."""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any, Iterator

import requests

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_BASE_URL = "https://api.github.com"
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_MAX = 60.0


class RateLimitError(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, reset_time: int | None = None):
        self.reset_time = reset_time
        super().__init__(f"Rate limit exceeded. Resets at {reset_time}")


class GitHubAPIError(Exception):
    """Raised when GitHub API returns an error."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"GitHub API error {status_code}: {message}")


class GitHubAPIClient:
    """GitHub REST API client with rate limiting and retry support.

    Features:
    - Automatic token authentication from environment
    - Rate limit handling with exponential backoff
    - Retry on transient errors (5xx, connection errors)
    - Pagination support

    Example:
        >>> client = GitHubAPIClient()
        >>> repo = client.get("/repos/owner/repo")
        >>> for issue in client.get_paginated("/repos/owner/repo/issues"):
        ...     print(issue["title"])
    """

    def __init__(
        self,
        token: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        """Initialize the GitHub API client.

        Args:
            token: GitHub personal access token. If None, uses GITHUB_TOKEN env var.
            base_url: GitHub API base URL.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retries for failed requests.
        """
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "ee-bench/0.1",
            }
        )
        if self.token:
            self.session.headers["Authorization"] = f"token {self.token}"

    def get(self, endpoint: str, **params: Any) -> dict[str, Any]:
        """Make a GET request to the GitHub API.

        Args:
            endpoint: API endpoint (e.g., "/repos/owner/repo").
            **params: Query parameters.

        Returns:
            JSON response as dictionary.

        Raises:
            GitHubAPIError: If the request fails after retries.
            RateLimitError: If rate limit is exceeded and cannot be waited out.
        """
        url = f"{self.base_url}{endpoint}"
        return self._request_with_retry("GET", url, params=params)

    def get_paginated(
        self, endpoint: str, per_page: int = 100, **params: Any
    ) -> Iterator[dict[str, Any]]:
        """Make paginated GET requests to the GitHub API.

        Automatically follows Link headers to fetch all pages.

        Args:
            endpoint: API endpoint.
            per_page: Number of items per page (max 100).
            **params: Additional query parameters.

        Yields:
            Individual items from all pages.
        """
        params["per_page"] = min(per_page, 100)
        url = f"{self.base_url}{endpoint}"

        while url:
            response = self._request_with_retry("GET", url, params=params, return_response=True)
            data = response.json()

            # Yield items
            if isinstance(data, list):
                yield from data
            else:
                yield data

            # Check for next page
            url = None
            params = {}  # Clear params for subsequent requests (they're in the Link URL)
            link_header = response.headers.get("Link", "")
            for link in link_header.split(","):
                if 'rel="next"' in link:
                    # Extract URL from <url>; rel="next"
                    url = link.split(";")[0].strip()[1:-1]
                    break

    def get_diff(self, endpoint: str) -> str:
        """Get a diff/patch from GitHub API.

        Args:
            endpoint: API endpoint for the diff.

        Returns:
            Diff content as string.
        """
        url = f"{self.base_url}{endpoint}"
        headers = {"Accept": "application/vnd.github.v3.diff"}
        response = self._request_with_retry(
            "GET", url, headers=headers, return_response=True
        )
        return response.text

    def _request_with_retry(
        self,
        method: str,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        return_response: bool = False,
    ) -> Any:
        """Make a request with retry logic.

        Args:
            method: HTTP method.
            url: Full URL.
            params: Query parameters.
            headers: Additional headers.
            return_response: If True, return Response object instead of JSON.

        Returns:
            JSON data or Response object.

        Raises:
            GitHubAPIError: If request fails after all retries.
        """
        last_exception = None
        backoff = DEFAULT_BACKOFF_BASE

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                )

                # Check for rate limiting
                if response.status_code in (403, 429):
                    remaining = response.headers.get("X-RateLimit-Remaining", "1")
                    if remaining == "0" or response.status_code == 429:
                        reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
                        wait_time = max(reset_time - time.time(), 0) + 1
                        if wait_time < DEFAULT_BACKOFF_MAX:
                            logger.warning(
                                f"Rate limited. Waiting {wait_time:.1f}s..."
                            )
                            time.sleep(wait_time)
                            continue
                        raise RateLimitError(reset_time)

                # Check for server errors (retry)
                if response.status_code >= 500:
                    raise requests.RequestException(
                        f"Server error: {response.status_code}"
                    )

                # Check for client errors (don't retry)
                if response.status_code >= 400:
                    raise GitHubAPIError(
                        response.status_code,
                        response.json().get("message", response.text),
                    )

                # Success
                if return_response:
                    return response
                return response.json()

            except (requests.RequestException, requests.Timeout) as e:
                last_exception = e
                if attempt < self.max_retries:
                    # Exponential backoff with jitter
                    sleep_time = backoff + random.uniform(0, backoff * 0.1)
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{self.max_retries + 1}): {e}. "
                        f"Retrying in {sleep_time:.1f}s..."
                    )
                    time.sleep(sleep_time)
                    backoff = min(backoff * 2, DEFAULT_BACKOFF_MAX)

        raise GitHubAPIError(0, f"Request failed after {self.max_retries + 1} attempts: {last_exception}")

    def get_org_repos(self, org: str) -> Iterator[dict[str, Any]]:
        """Get all repositories for an organization.

        Args:
            org: Organization name.

        Yields:
            Repository dictionaries.
        """
        yield from self.get_paginated(f"/orgs/{org}/repos", type="all")

    def get_user_repos(self, user: str) -> Iterator[dict[str, Any]]:
        """Get all repositories for a user.

        Args:
            user: Username.

        Yields:
            Repository dictionaries.
        """
        yield from self.get_paginated(f"/users/{user}/repos", type="all")

    def get_repos(self, owner: str) -> Iterator[dict[str, Any]]:
        """Get all repositories for an owner (user or organization).

        Tries organization endpoint first, falls back to user endpoint.

        Args:
            owner: Owner name (user or organization).

        Yields:
            Repository dictionaries.
        """
        try:
            yield from self.get_org_repos(owner)
        except GitHubAPIError as e:
            # If org not found, try user repos
            if e.status_code == 404:
                yield from self.get_user_repos(owner)
            else:
                raise

    def search_issues(
        self, query: str, per_page: int = 100
    ) -> Iterator[dict[str, Any]]:
        """Search issues and pull requests using GitHub Search API.

        Note: The Search API has stricter rate limits (30 req/min for
        authenticated users, 10 req/min for unauthenticated).

        Args:
            query: GitHub search query string (e.g., "is:pr is:merged repo:owner/repo").
            per_page: Number of results per page (max 100).

        Yields:
            Issue/PR dictionaries from search results.

        Example:
            >>> for pr in client.search_issues("is:pr is:merged label:bug repo:apache/kafka"):
            ...     print(pr["number"], pr["title"])
        """
        params = {"q": query, "per_page": min(per_page, 100)}
        url = f"{self.base_url}/search/issues"

        while url:
            response = self._request_with_retry(
                "GET", url, params=params, return_response=True
            )
            data = response.json()

            # Search API returns items in "items" array
            items = data.get("items", [])
            yield from items

            # Check for next page
            url = None
            params = {}  # Clear params for subsequent requests
            link_header = response.headers.get("Link", "")
            for link in link_header.split(","):
                if 'rel="next"' in link:
                    url = link.split(";")[0].strip()[1:-1]
                    break
