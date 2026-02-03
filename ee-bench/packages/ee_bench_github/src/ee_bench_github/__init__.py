"""ee_bench_github - GitHub providers for ee_bench_generator.

This package provides data providers that fetch issues and pull requests
from the GitHub API.
"""

from ee_bench_github.issues_provider import GitHubIssuesProvider
from ee_bench_github.pull_requests_provider import GitHubPullRequestsProvider

# New modules for enhanced functionality
from ee_bench_github.build_system import (
    BUILD_SYSTEM_GRADLE,
    BUILD_SYSTEM_GRADLE_KOTLIN,
    BUILD_SYSTEM_MAVEN,
    BUILD_SYSTEM_UNKNOWN,
    detect_build_system,
    is_gradle_project,
    is_maven_project,
)
from ee_bench_github.commit_fetcher import (
    CommitInfo,
    FetchedCommits,
    fetch_commits_for_issue,
    fetch_commits_from_timeline,
    filter_commits_by_branch,
    generate_combined_patch,
    get_base_commit,
    parse_commits_from_text,
    verify_commit_exists,
)
from ee_bench_github.test_field_parser import (
    ParsedTestFields,
    TextSource,
    extract_metadata,
    fetch_test_fields_for_issue,
    fetch_test_fields_from_commits,
    fetch_test_fields_from_issue,
    parse_test_fields,
    parse_test_fields_from_sources,
)

__version__ = "0.1.0"

__all__ = [
    # Providers
    "GitHubIssuesProvider",
    "GitHubPullRequestsProvider",
    # Commit fetching
    "CommitInfo",
    "FetchedCommits",
    "fetch_commits_for_issue",
    "fetch_commits_from_timeline",
    "filter_commits_by_branch",
    "generate_combined_patch",
    "get_base_commit",
    "parse_commits_from_text",
    "verify_commit_exists",
    # Build system detection
    "BUILD_SYSTEM_GRADLE",
    "BUILD_SYSTEM_GRADLE_KOTLIN",
    "BUILD_SYSTEM_MAVEN",
    "BUILD_SYSTEM_UNKNOWN",
    "detect_build_system",
    "is_gradle_project",
    "is_maven_project",
    # Test field parsing
    "ParsedTestFields",
    "TextSource",
    "extract_metadata",
    "fetch_test_fields_for_issue",
    "fetch_test_fields_from_commits",
    "fetch_test_fields_from_issue",
    "parse_test_fields",
    "parse_test_fields_from_sources",
]
