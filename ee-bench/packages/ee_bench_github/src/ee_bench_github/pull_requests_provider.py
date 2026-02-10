"""GitHub Pull Requests provider implementation."""

from __future__ import annotations

from typing import Any, Iterator

from ee_bench_generator import Provider
from ee_bench_generator.errors import ProviderError
from ee_bench_generator.metadata import Context, FieldDescriptor, ProviderMetadata

from ee_bench_github.api import GitHubAPIClient, GitHubAPIError
from ee_bench_github.pattern_matcher import expand_repo_pattern, is_pattern
from ee_bench_github.test_field_parser import parse_test_fields


class GitHubPullRequestsProvider(Provider):
    """Provider that fetches data from GitHub Pull Requests.

    This provider extracts all data needed for dataset generation directly
    from pull requests, including test fields parsed from the PR body.

    Provided fields:
    - description (pull_request): PR body text
    - title (pull_request): PR title
    - labels (pull_request): List of label names
    - number (pull_request): PR number
    - base_commit (pull_request): Base branch SHA
    - head_commit (pull_request): Head branch SHA
    - commits (pull_request): List of commit SHAs
    - patch (pull_request): Combined diff of all changes
    - FAIL_TO_PASS (pull_request): Parsed test field from body
    - PASS_TO_PASS (pull_request): Parsed test field from body
    - metadata (pull_request): Parsed <!--METADATA--> block from body as dict
    - repo_tree (repository): List of file paths at base commit
    - repo_url (repository): Repository clone URL
    """

    def __init__(self) -> None:
        self._client: GitHubAPIClient | None = None
        self._options: dict[str, Any] = {}
        self._cache: dict[str, Any] = {}

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="github_pull_requests",
            sources=["pull_request", "repository"],
            provided_fields=[
                FieldDescriptor(
                    "description",
                    source="pull_request",
                    description="PR body text",
                ),
                FieldDescriptor(
                    "title",
                    source="pull_request",
                    description="PR title",
                ),
                FieldDescriptor(
                    "labels",
                    source="pull_request",
                    description="List of label names",
                ),
                FieldDescriptor(
                    "number",
                    source="pull_request",
                    description="PR number",
                ),
                FieldDescriptor(
                    "base_commit",
                    source="pull_request",
                    description="Base branch SHA",
                ),
                FieldDescriptor(
                    "head_commit",
                    source="pull_request",
                    description="Head branch SHA",
                ),
                FieldDescriptor(
                    "commits",
                    source="pull_request",
                    description="List of commit SHAs in the PR",
                ),
                FieldDescriptor(
                    "patch",
                    source="pull_request",
                    description="Combined diff of all changes",
                ),
                FieldDescriptor(
                    "FAIL_TO_PASS",
                    source="pull_request",
                    description="Tests that should fail then pass (from PR body)",
                ),
                FieldDescriptor(
                    "PASS_TO_PASS",
                    source="pull_request",
                    description="Tests that should always pass (from PR body)",
                ),
                FieldDescriptor(
                    "metadata",
                    source="pull_request",
                    description="Parsed <!--METADATA--> block from PR body as dict",
                ),
                FieldDescriptor(
                    "repo_tree",
                    source="repository",
                    description="List of file paths in the repository at base commit",
                ),
                FieldDescriptor(
                    "repo_url",
                    source="repository",
                    description="Repository clone URL",
                ),
            ],
        )

    def prepare(self, **options: Any) -> None:
        """Prepare the provider for use.

        Args:
            **options: Provider options including:
                - token: GitHub API token (or uses GITHUB_TOKEN env var)
                - base_url: GitHub API base URL
                - timeout: Request timeout in seconds
        """
        self._options = options
        self._client = GitHubAPIClient(
            token=options.get("token"),
            base_url=options.get("base_url", "https://api.github.com"),
            timeout=options.get("timeout", 30),
        )
        self._cache = {}

    def get_field(self, name: str, source: str, context: Context) -> Any:
        """Retrieve a specific field value.

        Args:
            name: Field name.
            source: Data source.
            context: Runtime context with current_item set.

        Returns:
            Field value.

        Raises:
            ProviderError: If field cannot be retrieved.
        """
        if self._client is None:
            raise ProviderError("Provider not prepared. Call prepare() first.")

        current = context.current_item
        if not current:
            raise ProviderError("No current item in context")

        owner = current.get("owner")
        repo = current.get("repo")
        pr_number = current.get("number")

        if source == "pull_request":
            return self._get_pr_field(name, owner, repo, pr_number)
        elif source == "repository":
            return self._get_repo_field(name, owner, repo, pr_number)
        else:
            raise ProviderError(f"Unknown source: {source}")

    def _get_pr_field(
        self, name: str, owner: str, repo: str, pr_number: int
    ) -> Any:
        """Get a field from pull request data."""
        # Fields that don't need PR data
        if name == "patch":
            return self._get_pr_diff(owner, repo, pr_number)
        elif name == "commits":
            return self._get_pr_commits(owner, repo, pr_number)
        elif name == "number":
            return pr_number

        # Fields that need PR data
        pr = self._get_pr(owner, repo, pr_number)

        if name == "description":
            return pr.get("body") or ""
        elif name == "title":
            return pr.get("title") or ""
        elif name == "labels":
            return [label["name"] for label in pr.get("labels", [])]
        elif name == "base_commit":
            return pr["base"]["sha"]
        elif name == "head_commit":
            return pr["head"]["sha"]
        elif name == "FAIL_TO_PASS":
            body = pr.get("body") or ""
            return parse_test_fields(body).fail_to_pass
        elif name == "PASS_TO_PASS":
            body = pr.get("body") or ""
            return parse_test_fields(body).pass_to_pass
        elif name == "metadata":
            body = pr.get("body") or ""
            return self._parse_metadata_block(body)
        else:
            raise ProviderError(f"Unknown pull_request field: {name}")

    def _get_repo_field(
        self, name: str, owner: str, repo: str, pr_number: int
    ) -> Any:
        """Get a field from repository data."""
        if name == "repo_tree":
            # Get tree at base commit
            pr = self._get_pr(owner, repo, pr_number)
            base_sha = pr["base"]["sha"]
            return self._get_repo_tree(owner, repo, base_sha)
        elif name == "repo_url":
            return f"https://github.com/{owner}/{repo}.git"
        else:
            raise ProviderError(f"Unknown repository field: {name}")

    def _get_pr(self, owner: str, repo: str, pr_number: int) -> dict[str, Any]:
        """Get PR data, with caching."""
        cache_key = f"pr:{owner}/{repo}#{pr_number}"
        if cache_key not in self._cache:
            try:
                self._cache[cache_key] = self._client.get(
                    f"/repos/{owner}/{repo}/pulls/{pr_number}"
                )
            except GitHubAPIError as e:
                raise ProviderError(f"Failed to fetch PR: {e}")
        return self._cache[cache_key]

    def _get_pr_commits(self, owner: str, repo: str, pr_number: int) -> list[str]:
        """Get list of commit SHAs in the PR."""
        cache_key = f"pr_commits:{owner}/{repo}#{pr_number}"
        if cache_key not in self._cache:
            try:
                commits = list(
                    self._client.get_paginated(
                        f"/repos/{owner}/{repo}/pulls/{pr_number}/commits"
                    )
                )
                self._cache[cache_key] = [c["sha"] for c in commits]
            except GitHubAPIError as e:
                raise ProviderError(f"Failed to fetch PR commits: {e}")
        return self._cache[cache_key]

    def _get_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """Get the combined diff for the PR."""
        cache_key = f"pr_diff:{owner}/{repo}#{pr_number}"
        if cache_key not in self._cache:
            try:
                self._cache[cache_key] = self._client.get_diff(
                    f"/repos/{owner}/{repo}/pulls/{pr_number}"
                )
            except GitHubAPIError as e:
                raise ProviderError(f"Failed to fetch PR diff: {e}")
        return self._cache[cache_key]

    def _get_repo_tree(self, owner: str, repo: str, ref: str) -> list[str]:
        """Get repository file tree."""
        cache_key = f"tree:{owner}/{repo}@{ref}"
        if cache_key not in self._cache:
            try:
                tree_data = self._client.get(
                    f"/repos/{owner}/{repo}/git/trees/{ref}",
                    recursive="true",
                )
                self._cache[cache_key] = [
                    item["path"]
                    for item in tree_data.get("tree", [])
                    if item["type"] == "blob"
                ]
            except GitHubAPIError as e:
                raise ProviderError(f"Failed to fetch repo tree: {e}")
        return self._cache[cache_key]

    @staticmethod
    def _parse_metadata_block(body: str) -> dict[str, str]:
        """Parse <!--METADATA ... METADATA--> block from PR body.

        Args:
            body: PR body text.

        Returns:
            Dictionary of key-value pairs from the metadata block.
            Empty dict if no metadata block found.
        """
        import re

        pattern = re.compile(r"<!--METADATA\n(.*?)\nMETADATA-->", re.DOTALL)
        match = pattern.search(body)
        if not match:
            return {}

        content = match.group(1)
        result = {}
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            colon_idx = line.find(":")
            if colon_idx < 0:
                continue
            key = line[:colon_idx].strip()
            value = line[colon_idx + 1:]
            value = value.replace("\\n", "\n")
            result[key] = value

        return result

    def _expand_pattern(self, pattern: str) -> list[str]:
        """Expand a wildcard pattern to matching repositories.

        Args:
            pattern: Repository pattern (e.g., "apache/*", "apache/kafka-*").

        Returns:
            List of matching "owner/repo" strings.
        """
        try:
            return expand_repo_pattern(pattern, self._client.get_repos)
        except Exception as e:
            raise ProviderError(f"Failed to expand pattern '{pattern}': {e}")

    def _resolve_repos(self, filters: dict[str, Any]) -> list[str]:
        """Resolve repository list from filters.

        Supports:
        - 'repo': Single repository (e.g., "owner/repo")
        - 'repos': Multiple repositories (e.g., ["owner/repo1", "owner/repo2"])
        - Wildcard patterns (e.g., "apache/*", "apache/kafka-*")

        Args:
            filters: Selection filters dict.

        Returns:
            List of "owner/repo" strings.

        Raises:
            ProviderError: If neither 'repo' nor 'repos' is specified.
        """
        raw_repos: list[str] = []

        # Check for 'repos' (plural) first
        if "repos" in filters:
            repos_value = filters["repos"]
            if isinstance(repos_value, list):
                raw_repos.extend(repos_value)
            else:
                raw_repos.append(repos_value)

        # Check for 'repo' (singular)
        if "repo" in filters:
            raw_repos.append(filters["repo"])

        if not raw_repos:
            raise ProviderError(
                "Selection must include 'repo' or 'repos' filter (owner/repo)"
            )

        # Expand any wildcard patterns
        resolved_repos: list[str] = []
        for repo in raw_repos:
            if is_pattern(repo):
                resolved_repos.extend(self._expand_pattern(repo))
            else:
                resolved_repos.append(repo)

        if not resolved_repos:
            raise ProviderError(
                "No repositories matched the specified pattern(s)"
            )

        return resolved_repos

    def _iter_repo_items(
        self,
        owner: str,
        repo: str,
        filters: dict[str, Any],
        limit: int | None,
        count: int,
    ) -> Iterator[tuple[dict[str, Any], int]]:
        """Iterate over items from a single repository.

        Args:
            owner: Repository owner.
            repo: Repository name.
            filters: Selection filters.
            limit: Maximum total items to return.
            count: Current item count.

        Yields:
            Tuples of (item_dict, new_count).
        """
        # If specific PR numbers provided
        pr_numbers = filters.get("pr_numbers", [])
        if pr_numbers:
            for num in pr_numbers:
                if limit and count >= limit:
                    return
                yield {"owner": owner, "repo": repo, "number": int(num)}, count + 1
                count += 1
            return

        # Otherwise, list PRs with filters
        params = {}
        if "state" in filters:
            params["state"] = filters["state"]

        for pr in self._client.get_paginated(
            f"/repos/{owner}/{repo}/pulls", **params
        ):
            if limit and count >= limit:
                return

            # Filter by labels if specified
            if "labels" in filters:
                pr_labels = {label["name"] for label in pr.get("labels", [])}
                if not pr_labels.intersection(filters["labels"]):
                    continue

            yield {"owner": owner, "repo": repo, "number": pr["number"]}, count + 1
            count += 1

    def _iter_from_search(
        self, query: str, limit: int | None
    ) -> Iterator[dict[str, Any]]:
        """Iterate over items from GitHub Search API.

        Args:
            query: GitHub search query string.
            limit: Maximum items to return.

        Yields:
            Dictionaries with owner, repo, number keys.
        """
        count = 0

        for item in self._client.search_issues(query):
            if limit and count >= limit:
                return

            # Skip non-PRs (search_issues returns both issues and PRs)
            if "pull_request" not in item:
                continue

            # Extract owner/repo from repository_url
            # Format: "https://api.github.com/repos/owner/repo"
            repo_url = item.get("repository_url", "")
            parts = repo_url.split("/repos/")
            if len(parts) < 2:
                continue

            owner_repo = parts[1]
            owner, repo = owner_repo.split("/", 1)

            yield {"owner": owner, "repo": repo, "number": item["number"]}
            count += 1

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:
        """Iterate over selected pull requests.

        Selection filters:
        - query: GitHub search query (mutually exclusive with repo/repos)
        - repo: "owner/repo" (single repo)
        - repos: ["owner/repo1", "owner/repo2"] (multiple repos)
        - pr_numbers: List of PR numbers to fetch (only for single repo)
        - state: PR state filter ("open", "closed", "all")
        - labels: Filter by label names

        Yields:
            Dictionaries with owner, repo, number keys.
        """
        if self._client is None:
            raise ProviderError("Provider not prepared. Call prepare() first.")

        filters = context.selection.filters
        limit = context.selection.limit

        # Check for search query - mutually exclusive with repo/repos
        if "query" in filters:
            if "repo" in filters or "repos" in filters:
                raise ProviderError(
                    "Cannot use 'query' filter together with 'repo' or 'repos'. "
                    "Use repo: in the search query string instead."
                )
            yield from self._iter_from_search(filters["query"], limit)
            return

        # Standard repo-based iteration
        repos = self._resolve_repos(filters)
        count = 0

        for repo_full in repos:
            owner, repo = repo_full.split("/", 1)

            for item, new_count in self._iter_repo_items(
                owner, repo, filters, limit, count
            ):
                yield item
                count = new_count

                if limit and count >= limit:
                    return
