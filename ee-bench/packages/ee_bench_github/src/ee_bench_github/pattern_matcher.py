"""Pattern matching utilities for repository names.

Supports wildcard patterns like:
- "apache/*" - all repos in the apache organization
- "apache/kafka-*" - repos matching kafka-* in apache org
"""

from __future__ import annotations

import fnmatch
from typing import Any, Callable, Iterator


def is_pattern(value: str) -> bool:
    """Check if a value contains wildcard patterns.

    Args:
        value: String to check.

    Returns:
        True if the value contains wildcard characters (* or ?).

    Example:
        >>> is_pattern("apache/kafka")
        False
        >>> is_pattern("apache/*")
        True
        >>> is_pattern("apache/kafka-*")
        True
    """
    return "*" in value or "?" in value


def match_pattern(pattern: str, values: list[str]) -> list[str]:
    """Filter values that match a fnmatch pattern.

    Args:
        pattern: Pattern with wildcards.
        values: List of strings to filter.

    Returns:
        List of values that match the pattern.

    Example:
        >>> match_pattern("kafka-*", ["kafka-clients", "kafka-streams", "flink"])
        ['kafka-clients', 'kafka-streams']
    """
    return [v for v in values if fnmatch.fnmatch(v, pattern)]


def expand_repo_pattern(
    pattern: str,
    get_repos: Callable[[str], Iterator[dict[str, Any]]],
) -> list[str]:
    """Expand a repository pattern to a list of matching repos.

    Supports patterns like:
    - "org/*" - all repos in the organization
    - "org/prefix-*" - repos matching the pattern

    Args:
        pattern: Repository pattern (e.g., "apache/*", "apache/kafka-*").
        get_repos: Callable that takes org/user name and returns repo dicts.
            Each dict should have a "name" or "full_name" key.

    Returns:
        List of full repository names ("owner/repo").

    Example:
        >>> def mock_get_repos(org):
        ...     return iter([{"name": "kafka"}, {"name": "flink"}])
        >>> expand_repo_pattern("apache/*", mock_get_repos)
        ['apache/kafka', 'apache/flink']
    """
    if "/" not in pattern:
        raise ValueError(f"Invalid repo pattern: '{pattern}'. Must be 'owner/repo' format.")

    owner, repo_pattern = pattern.split("/", 1)

    # If no wildcard in owner part, we can proceed
    if is_pattern(owner):
        raise ValueError(
            f"Wildcards in owner/org name are not supported: '{pattern}'"
        )

    # Get all repos for the owner
    all_repos = []
    for repo in get_repos(owner):
        # Handle both "name" and "full_name" formats
        repo_name = repo.get("name") or repo.get("full_name", "").split("/")[-1]
        all_repos.append(repo_name)

    # If repo part is a wildcard, return all repos
    if repo_pattern == "*":
        return [f"{owner}/{name}" for name in all_repos]

    # Otherwise, filter by pattern
    matched = match_pattern(repo_pattern, all_repos)
    return [f"{owner}/{name}" for name in matched]
