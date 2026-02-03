"""GitHub Issues provider implementation."""

from __future__ import annotations

import logging
from typing import Any, Iterator

from ee_bench_generator import Provider
from ee_bench_generator.errors import ProviderError
from ee_bench_generator.metadata import Context, FieldDescriptor, ProviderMetadata

from ee_bench_github.api import GitHubAPIClient, GitHubAPIError
from ee_bench_github.build_system import detect_build_system
from ee_bench_github.commit_fetcher import (
    fetch_commits_for_issue,
    generate_combined_patch,
)
from ee_bench_github.pattern_matcher import expand_repo_pattern, is_pattern
from ee_bench_github.test_field_parser import fetch_test_fields_for_issue

logger = logging.getLogger(__name__)


class GitHubIssuesProvider(Provider):
    """Provider that fetches data from GitHub Issues.

    This provider supports both the legacy workflow (basic issue data) and
    enhanced workflow with commit fetching, patch generation, and test field parsing.

    Provided fields:
    - description (issue): Issue body text
    - title (issue): Issue title
    - labels (issue): List of label names
    - number (issue): Issue number
    - commits (issue): List of linked commit SHAs (requires fetch_commits=true)
    - base_commit (issue): Parent of earliest commit (requires fetch_commits=true)
    - patch (issue): Combined diff from commits (requires fetch_commits=true)
    - FAIL_TO_PASS (issue): Tests from body/comments (requires parse_comments=true)
    - PASS_TO_PASS (issue): Tests from body/comments (requires parse_comments=true)
    - build_system (repository): Build system type (requires detect_build_system=true)
    - repo_tree (repository): List of file paths in the repo
    - repo_url (repository): Repository clone URL

    Provider options:
    - fetch_commits: Enable commit fetching from Timeline API (default: false)
    - parse_comments: Parse test fields from comments (default: false)
    - detect_build_system: Detect Maven/Gradle build system (default: false)
    - token: GitHub API token (or uses GITHUB_TOKEN env var)
    - base_url: GitHub API base URL
    - timeout: Request timeout in seconds
    """

    def __init__(self) -> None:
        self._client: GitHubAPIClient | None = None
        self._options: dict[str, Any] = {}
        self._cache: dict[str, Any] = {}

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="github_issues",
            sources=["issue", "repository"],
            provided_fields=[
                # Basic issue fields
                FieldDescriptor(
                    "description",
                    source="issue",
                    description="Issue body text",
                ),
                FieldDescriptor(
                    "title",
                    source="issue",
                    description="Issue title",
                ),
                FieldDescriptor(
                    "labels",
                    source="issue",
                    description="List of label names",
                ),
                FieldDescriptor(
                    "number",
                    source="issue",
                    description="Issue number",
                ),
                # Enhanced fields (commit-related)
                FieldDescriptor(
                    "commits",
                    source="issue",
                    description="List of linked commit SHAs",
                ),
                FieldDescriptor(
                    "base_commit",
                    source="issue",
                    description="Parent of earliest commit (patch base)",
                ),
                FieldDescriptor(
                    "patch",
                    source="issue",
                    description="Combined diff from linked commits",
                ),
                # Test fields
                FieldDescriptor(
                    "FAIL_TO_PASS",
                    source="issue",
                    description="Tests that should fail then pass (JSON array)",
                ),
                FieldDescriptor(
                    "PASS_TO_PASS",
                    source="issue",
                    description="Tests that should always pass (JSON array)",
                ),
                # Repository fields
                FieldDescriptor(
                    "build_system",
                    source="repository",
                    description="Build system type (maven|gradle|gradle-kotlin)",
                ),
                FieldDescriptor(
                    "repo_tree",
                    source="repository",
                    description="List of file paths in the repository",
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
                - fetch_commits: Enable commit fetching (default: false)
                - parse_comments: Parse test fields from comments (default: false)
                - detect_build_system: Detect build system (default: false)
        """
        self._options = options
        self._client = GitHubAPIClient(
            token=options.get("token"),
            base_url=options.get("base_url", "https://api.github.com"),
            timeout=options.get("timeout", 30),
        )
        self._cache = {}

    def _should_fetch_commits(self) -> bool:
        """Check if commit fetching is enabled."""
        return self._options.get("fetch_commits", False) in (True, "true", "True", "1")

    def _should_parse_comments(self) -> bool:
        """Check if comment parsing is enabled."""
        return self._options.get("parse_comments", False) in (True, "true", "True", "1")

    def _should_detect_build_system(self) -> bool:
        """Check if build system detection is enabled."""
        return self._options.get("detect_build_system", False) in (True, "true", "True", "1")

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
        issue_number = current.get("number")

        if source == "issue":
            return self._get_issue_field(name, owner, repo, issue_number, context)
        elif source == "repository":
            return self._get_repo_field(name, owner, repo, context)
        else:
            raise ProviderError(f"Unknown source: {source}")

    def _get_issue_field(
        self, name: str, owner: str, repo: str, issue_number: int, context: Context
    ) -> Any:
        """Get a field from issue data."""
        issue = self._get_issue(owner, repo, issue_number)

        if name == "description":
            return issue.get("body") or ""
        elif name == "title":
            return issue.get("title") or ""
        elif name == "labels":
            return [label["name"] for label in issue.get("labels", [])]
        elif name == "number":
            return issue_number
        elif name == "commits":
            return self._get_commits(owner, repo, issue_number)
        elif name == "base_commit":
            return self._get_base_commit(owner, repo, issue_number)
        elif name == "patch":
            return self._get_patch(owner, repo, issue_number)
        elif name == "FAIL_TO_PASS":
            return self._get_test_field(owner, repo, issue_number, "fail_to_pass")
        elif name == "PASS_TO_PASS":
            return self._get_test_field(owner, repo, issue_number, "pass_to_pass")
        else:
            raise ProviderError(f"Unknown issue field: {name}")

    def _get_repo_field(
        self, name: str, owner: str, repo: str, context: Context
    ) -> Any:
        """Get a field from repository data."""
        if name == "repo_tree":
            ref = context.options.get("ref", "HEAD")
            return self._get_repo_tree(owner, repo, ref)
        elif name == "repo_url":
            return f"https://github.com/{owner}/{repo}.git"
        elif name == "build_system":
            return self._get_build_system(owner, repo, context)
        else:
            raise ProviderError(f"Unknown repository field: {name}")

    def _get_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        """Get issue data, with caching."""
        cache_key = f"issue:{owner}/{repo}#{issue_number}"
        if cache_key not in self._cache:
            try:
                self._cache[cache_key] = self._client.get(
                    f"/repos/{owner}/{repo}/issues/{issue_number}"
                )
            except GitHubAPIError as e:
                raise ProviderError(f"Failed to fetch issue: {e}")
        return self._cache[cache_key]

    def _get_fetched_commits(self, owner: str, repo: str, issue_number: int) -> Any:
        """Get fetched commits data, with caching."""
        cache_key = f"fetched_commits:{owner}/{repo}#{issue_number}"
        if cache_key not in self._cache:
            if not self._should_fetch_commits():
                raise ProviderError(
                    "Commit fetching is disabled. Enable with fetch_commits=true option."
                )
            try:
                self._cache[cache_key] = fetch_commits_for_issue(
                    self._client, owner, repo, issue_number
                )
            except Exception as e:
                logger.warning(f"Failed to fetch commits: {e}")
                raise ProviderError(f"Failed to fetch commits: {e}")
        return self._cache[cache_key]

    def _get_commits(self, owner: str, repo: str, issue_number: int) -> list[str]:
        """Get list of commit SHAs."""
        fetched = self._get_fetched_commits(owner, repo, issue_number)
        return fetched.commits

    def _get_base_commit(self, owner: str, repo: str, issue_number: int) -> str:
        """Get base commit SHA."""
        fetched = self._get_fetched_commits(owner, repo, issue_number)
        return fetched.base_commit

    def _get_patch(self, owner: str, repo: str, issue_number: int) -> str:
        """Get combined patch from commits."""
        cache_key = f"patch:{owner}/{repo}#{issue_number}"
        if cache_key not in self._cache:
            fetched = self._get_fetched_commits(owner, repo, issue_number)
            if not fetched.commits:
                self._cache[cache_key] = ""
            else:
                try:
                    self._cache[cache_key] = generate_combined_patch(
                        self._client, owner, repo, fetched.commits
                    )
                except Exception as e:
                    logger.warning(f"Failed to generate patch: {e}")
                    self._cache[cache_key] = ""
        return self._cache[cache_key]

    def _get_test_fields(self, owner: str, repo: str, issue_number: int) -> Any:
        """Get parsed test fields, with caching."""
        cache_key = f"test_fields:{owner}/{repo}#{issue_number}"
        if cache_key not in self._cache:
            if not self._should_parse_comments():
                # Return empty fields if parsing is disabled
                from ee_bench_github.test_field_parser import ParsedTestFields
                self._cache[cache_key] = ParsedTestFields(
                    fail_to_pass="[]", pass_to_pass="[]"
                )
            else:
                # Get commits if available for commit message parsing
                commit_shas = None
                if self._should_fetch_commits():
                    try:
                        fetched = self._get_fetched_commits(owner, repo, issue_number)
                        commit_shas = fetched.commits
                    except Exception:
                        pass

                try:
                    self._cache[cache_key] = fetch_test_fields_for_issue(
                        self._client, owner, repo, issue_number, commit_shas
                    )
                except Exception as e:
                    logger.warning(f"Failed to parse test fields: {e}")
                    from ee_bench_github.test_field_parser import ParsedTestFields
                    self._cache[cache_key] = ParsedTestFields(
                        fail_to_pass="[]", pass_to_pass="[]"
                    )
        return self._cache[cache_key]

    def _get_test_field(
        self, owner: str, repo: str, issue_number: int, field: str
    ) -> str:
        """Get a specific test field."""
        test_fields = self._get_test_fields(owner, repo, issue_number)
        return getattr(test_fields, field, "[]")

    def _get_build_system(self, owner: str, repo: str, context: Context) -> str:
        """Get build system type."""
        if not self._should_detect_build_system():
            return ""

        # Use base_commit as reference if available
        ref = None
        current = context.current_item
        if current:
            issue_number = current.get("number")
            if issue_number and self._should_fetch_commits():
                try:
                    fetched = self._get_fetched_commits(owner, repo, issue_number)
                    ref = fetched.base_commit
                except Exception:
                    pass

        cache_key = f"build_system:{owner}/{repo}@{ref or 'HEAD'}"
        if cache_key not in self._cache:
            try:
                self._cache[cache_key] = detect_build_system(
                    self._client, owner, repo, ref
                )
            except Exception as e:
                logger.warning(f"Failed to detect build system: {e}")
                self._cache[cache_key] = ""
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
        # If specific issue numbers provided
        issue_numbers = filters.get("issue_numbers", [])
        if issue_numbers:
            for num in issue_numbers:
                if limit and count >= limit:
                    return
                yield {"owner": owner, "repo": repo, "number": int(num)}, count + 1
                count += 1
            return

        # Otherwise, list issues with filters
        params = {}
        if "state" in filters:
            params["state"] = filters["state"]
        if "labels" in filters:
            params["labels"] = ",".join(filters["labels"])

        for issue in self._client.get_paginated(
            f"/repos/{owner}/{repo}/issues", **params
        ):
            if limit and count >= limit:
                return

            # Skip pull requests (they appear in issues API)
            if "pull_request" in issue:
                continue

            yield {"owner": owner, "repo": repo, "number": issue["number"]}, count + 1
            count += 1

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:
        """Iterate over selected issues.

        Selection filters:
        - repo: "owner/repo" (single repo)
        - repos: ["owner/repo1", "owner/repo2"] (multiple repos)
        - issue_numbers: List of issue numbers to fetch (only for single repo)
        - state: Issue state filter ("open", "closed", "all")
        - labels: Filter by label names

        Yields:
            Dictionaries with owner, repo, number keys.
        """
        if self._client is None:
            raise ProviderError("Provider not prepared. Call prepare() first.")

        filters = context.selection.filters
        repos = self._resolve_repos(filters)
        limit = context.selection.limit
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
