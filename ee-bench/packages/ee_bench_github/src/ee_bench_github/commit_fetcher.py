"""Commit fetching utilities for GitHub issues.

This module provides functions to fetch commits linked to GitHub issues through:
- GitHub's Timeline API (referenced commits)
- Manually linked commits in issue descriptions/comments
- Related pull requests
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ee_bench_github.api import GitHubAPIClient

logger = logging.getLogger(__name__)


@dataclass
class CommitInfo:
    """Information about a commit.

    Attributes:
        sha: Full commit SHA.
        date: Commit date (ISO8601 format).
        branches: List of branches containing this commit.
    """

    sha: str
    date: str
    branches: list[str]


@dataclass
class FetchedCommits:
    """Result of commit fetching operation.

    Attributes:
        commits: List of commit SHAs sorted by date (oldest first).
        latest_commit: The most recent commit SHA.
        base_commit: Parent of the earliest commit (for patch base).
    """

    commits: list[str]
    latest_commit: str
    base_commit: str


def fetch_commits_from_timeline(
    client: GitHubAPIClient, owner: str, repo: str, issue_number: int
) -> list[CommitInfo]:
    """Fetch commits linked to an issue via GitHub's Timeline API.

    Uses pagination to fetch all timeline events and extracts referenced commits.

    Args:
        client: GitHub API client.
        owner: Repository owner.
        repo: Repository name.
        issue_number: Issue number.

    Returns:
        List of CommitInfo objects from timeline events.
    """
    commits: list[CommitInfo] = []

    logger.debug(f"Fetching timeline events for {owner}/{repo}#{issue_number}")

    try:
        for event in client.get_paginated(
            f"/repos/{owner}/{repo}/issues/{issue_number}/timeline",
            per_page=100,
        ):
            if event.get("event") == "referenced" and event.get("commit_id"):
                commit_sha = event["commit_id"]
                created_at = event.get("created_at", "")

                commits.append(
                    CommitInfo(
                        sha=commit_sha,
                        date=created_at,
                        branches=[],
                    )
                )

        logger.debug(f"Found {len(commits)} referenced commits in timeline")
    except Exception as e:
        logger.warning(f"Failed to fetch timeline: {e}")

    return commits


def parse_commits_from_text(text: str) -> tuple[list[str], list[str], str | None]:
    """Parse commit hashes from text (issue body or comments).

    Extracts:
    - Full 40-character commit hashes
    - Commits marked with "Commit:" or "Related commit:" prefix
    - Excluded commits marked with "Excluded" or "Exclude" prefix
    - Manual base commit marked with "Base commit:" prefix

    Args:
        text: Text to parse (issue body or comment).

    Returns:
        Tuple of (commit_hashes, excluded_hashes, manual_base_commit).
    """
    if not text:
        return [], [], None

    commit_hashes: set[str] = set()
    excluded_hashes: set[str] = set()
    manual_base_commit: str | None = None

    # Pattern for excluded commits
    excluded_pattern = re.findall(r"[Ee]xclude[d]?\s+([0-9a-f]{7,40})", text)
    for commit_hash in excluded_pattern:
        excluded_hashes.add(commit_hash)

    # Pattern for manual base commit
    base_pattern = re.search(r"[Bb]ase\s+[Cc]ommit:?\s+([0-9a-f]{7,40})", text)
    if base_pattern:
        manual_base_commit = base_pattern.group(1)

    # Pattern 1: Common formats like "Related commit: HASH", "Commit: HASH"
    commit_pattern_1 = re.findall(
        r"(?:[Rr]elated\s+)?[Cc]ommit:?\s+([0-9a-f]{40})", text
    )
    commit_hashes.update(commit_pattern_1)

    # Pattern 2: Stand-alone SHA format (just the hash with 40 characters)
    commit_pattern_2 = re.findall(r"\b([0-9a-f]{40})\b", text)
    commit_hashes.update(commit_pattern_2)

    # Remove excluded commits from the result
    commit_hashes -= excluded_hashes

    return list(commit_hashes), list(excluded_hashes), manual_base_commit


def verify_commit_exists(
    client: GitHubAPIClient, owner: str, repo: str, commit_hash: str
) -> tuple[str, list[str]]:
    """Verify if a commit exists in the repository.

    Also determines which branches contain the commit.

    Args:
        client: GitHub API client.
        owner: Repository owner.
        repo: Repository name.
        commit_hash: Commit hash to verify (can be short or full).

    Returns:
        Tuple of (full_commit_hash, branches). Empty strings/list if not found.
    """
    if not commit_hash:
        return "", []

    # First, verify commit exists and get full hash
    try:
        commit_data = client.get(f"/repos/{owner}/{repo}/commits/{commit_hash}")
        full_sha = commit_data.get("sha", "")
    except Exception:
        return "", []

    if not full_sha:
        return "", []

    # Check which branches contain this commit
    branches: list[str] = []

    # Try branches-where-head API first
    try:
        head_branches = client.get(
            f"/repos/{owner}/{repo}/commits/{full_sha}/branches-where-head"
        )
        if isinstance(head_branches, list):
            branches = [b.get("name", "") for b in head_branches if b.get("name")]
            if branches:
                return full_sha, branches
    except Exception:
        pass

    # Fallback: check against repo's default branch
    try:
        repo_info = client.get(f"/repos/{owner}/{repo}")
        default_branch = repo_info.get("default_branch", "main")

        # Check if commit is reachable from default branch
        compare_data = client.get(
            f"/repos/{owner}/{repo}/compare/{full_sha}...{default_branch}"
        )
        status = compare_data.get("status", "")
        if status in ("ahead", "identical"):
            branches.append(default_branch)
    except Exception:
        pass

    return full_sha, branches


def filter_commits_by_branch(
    client: GitHubAPIClient,
    owner: str,
    repo: str,
    commits_with_branches: list[tuple[str, list[str]]],
) -> list[str]:
    """Filter commits to ensure they all belong to the same branch.

    Prioritizes the default branch (main/master) if available.

    Args:
        client: GitHub API client.
        owner: Repository owner.
        repo: Repository name.
        commits_with_branches: List of (commit_sha, branches) tuples.

    Returns:
        Filtered list of commit SHAs.
    """
    if len(commits_with_branches) <= 1:
        return [c[0] for c in commits_with_branches]

    # Get default branch
    try:
        repo_info = client.get(f"/repos/{owner}/{repo}")
        default_branch = repo_info.get("default_branch", "main")
    except Exception:
        default_branch = "main"

    # Count commits per branch
    branch_commit_count: dict[str, int] = {}
    for _, branches in commits_with_branches:
        for branch in branches:
            branch_commit_count[branch] = branch_commit_count.get(branch, 0) + 1

    # Prefer default branch if it contains any commits
    if default_branch in branch_commit_count:
        target_branch = default_branch
    elif branch_commit_count:
        target_branch = max(branch_commit_count, key=branch_commit_count.get)
    else:
        # No branch info available, return all commits
        return [c[0] for c in commits_with_branches]

    logger.debug(f"Filtering commits to branch: {target_branch}")

    # Filter commits that belong to the target branch
    filtered = []
    for commit_sha, branches in commits_with_branches:
        if target_branch in branches:
            filtered.append(commit_sha)
        else:
            logger.debug(
                f"Excluding commit {commit_sha[:7]} - not in branch '{target_branch}'"
            )

    return filtered


def get_base_commit(
    client: GitHubAPIClient,
    owner: str,
    repo: str,
    commits: list[str],
    manual_base: str | None = None,
) -> str:
    """Get the base commit (parent of earliest commit).

    Args:
        client: GitHub API client.
        owner: Repository owner.
        repo: Repository name.
        commits: List of commit SHAs (sorted by date, oldest first).
        manual_base: Optional manually specified base commit.

    Returns:
        Base commit SHA, or empty string if not found.
    """
    # Use manual base if provided
    if manual_base:
        full_sha, _ = verify_commit_exists(client, owner, repo, manual_base)
        if full_sha:
            logger.debug(f"Using manual base commit: {full_sha[:7]}")
            return full_sha

    if not commits:
        return ""

    # Get parent of earliest commit
    earliest_commit = commits[0]

    try:
        commit_data = client.get(f"/repos/{owner}/{repo}/commits/{earliest_commit}")
        parents = commit_data.get("parents", [])
        if parents:
            base_sha = parents[0].get("sha", "")
            logger.debug(f"Base commit (parent of {earliest_commit[:7]}): {base_sha[:7]}")
            return base_sha
    except Exception as e:
        logger.warning(f"Failed to get base commit: {e}")

    return ""


def generate_combined_patch(
    client: GitHubAPIClient, owner: str, repo: str, commits: list[str]
) -> str:
    """Generate a combined patch from multiple commits.

    Fetches the diff for each commit and combines them into a single patch.
    Handles merging of patches for the same file across commits.

    Args:
        client: GitHub API client.
        owner: Repository owner.
        repo: Repository name.
        commits: List of commit SHAs to include in patch.

    Returns:
        Combined patch string in unified diff format.
    """
    if not commits:
        return ""

    # Dictionary to store patches by file path
    file_patches: dict[str, list[str]] = {}

    for commit_sha in commits:
        try:
            patch = client.get_diff(f"/repos/{owner}/{repo}/commits/{commit_sha}")
            if not patch:
                continue

            # Split into individual file diffs
            file_diffs = re.split(r"(diff --git )", patch)

            for i in range(1, len(file_diffs), 2):
                if i + 1 < len(file_diffs):
                    diff = file_diffs[i] + file_diffs[i + 1]

                    # Extract file path
                    file_path_match = re.search(r"diff --git a/(.*) b/", diff)
                    if file_path_match:
                        file_path = file_path_match.group(1)

                        if file_path not in file_patches:
                            file_patches[file_path] = []
                        file_patches[file_path].append(diff)

        except Exception as e:
            logger.warning(f"Failed to get patch for commit {commit_sha[:7]}: {e}")

    if not file_patches:
        return ""

    # Merge patches for each file
    merged_patches = []
    for file_path, patches in file_patches.items():
        merged = _merge_file_patches(patches)
        if merged:
            merged_patches.append(merged)
            logger.debug(f"Merged {len(patches)} patches for: {file_path}")

    combined = "\n\n".join(merged_patches)

    # Ensure patch ends with newline
    if combined and not combined.endswith("\n"):
        combined += "\n"

    return combined


def _merge_file_patches(patches: list[str]) -> str:
    """Merge multiple patches for the same file.

    We preserve each "diff --git" block intact and return them in order,
    allowing patch tools to apply them sequentially.

    Args:
        patches: List of patch strings for the same file.

    Returns:
        Concatenated patch blocks.
    """
    patches = [p for p in patches if p and p.strip()]
    if not patches:
        return ""

    if len(patches) == 1:
        return patches[0]

    # Deduplicate while preserving order
    sanitized = []
    seen: set[str] = set()
    for p in patches:
        match = re.search(r"(diff --git[^\n]*\n.*)", p.strip(), re.DOTALL)
        block = match.group(1) if match else p.strip()
        if block and block not in seen:
            sanitized.append(block)
            seen.add(block)

    return "\n\n".join(sanitized)


def fetch_commits_for_issue(
    client: GitHubAPIClient,
    owner: str,
    repo: str,
    issue_number: int,
) -> FetchedCommits:
    """Fetch all commits related to a GitHub issue.

    This is the main entry point that combines all commit fetching strategies:
    1. Timeline API (referenced commits)
    2. Issue body parsing
    3. Issue comments parsing
    4. Related PRs (fallback)

    Args:
        client: GitHub API client.
        owner: Repository owner.
        repo: Repository name.
        issue_number: Issue number.

    Returns:
        FetchedCommits with sorted commits, latest commit, and base commit.
    """
    all_commits: list[CommitInfo] = []
    excluded_hashes: set[str] = set()
    manual_base_commit: str | None = None

    # 1. Fetch commits from timeline API
    timeline_commits = fetch_commits_from_timeline(client, owner, repo, issue_number)
    all_commits.extend(timeline_commits)

    # 2. Parse commits from issue body
    try:
        issue_data = client.get(f"/repos/{owner}/{repo}/issues/{issue_number}")
        issue_body = issue_data.get("body", "") or ""

        body_commits, body_excluded, body_base = parse_commits_from_text(issue_body)
        excluded_hashes.update(body_excluded)
        if body_base:
            manual_base_commit = body_base

        for commit_hash in body_commits:
            full_sha, branches = verify_commit_exists(client, owner, repo, commit_hash)
            if full_sha:
                # Get commit date
                try:
                    commit_data = client.get(f"/repos/{owner}/{repo}/commits/{full_sha}")
                    date = (
                        commit_data.get("commit", {})
                        .get("committer", {})
                        .get("date", "")
                    )
                    all_commits.append(CommitInfo(sha=full_sha, date=date, branches=branches))
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Failed to parse issue body: {e}")

    # 3. Parse commits from issue comments
    try:
        for comment in client.get_paginated(
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments"
        ):
            comment_body = comment.get("body", "") or ""
            comment_commits, comment_excluded, comment_base = parse_commits_from_text(
                comment_body
            )
            excluded_hashes.update(comment_excluded)
            if comment_base and not manual_base_commit:
                manual_base_commit = comment_base

            for commit_hash in comment_commits:
                if any(commit_hash.startswith(exc) for exc in excluded_hashes):
                    continue

                full_sha, branches = verify_commit_exists(
                    client, owner, repo, commit_hash
                )
                if full_sha and full_sha not in excluded_hashes:
                    try:
                        commit_data = client.get(
                            f"/repos/{owner}/{repo}/commits/{full_sha}"
                        )
                        date = (
                            commit_data.get("commit", {})
                            .get("committer", {})
                            .get("date", "")
                        )
                        all_commits.append(
                            CommitInfo(sha=full_sha, date=date, branches=branches)
                        )
                    except Exception:
                        pass
    except Exception as e:
        logger.warning(f"Failed to parse issue comments: {e}")

    # 4. If no commits found, try related PRs
    if not all_commits:
        logger.debug("No commits found, checking related PRs")
        try:
            for event in client.get_paginated(
                f"/repos/{owner}/{repo}/issues/{issue_number}/timeline"
            ):
                if (
                    event.get("event") == "cross-referenced"
                    and event.get("source", {}).get("issue", {}).get("pull_request")
                ):
                    source = event.get("source", {})
                    issue = source.get("issue", {})
                    pr_repo = issue.get("repository", {})

                    if (
                        pr_repo.get("owner", {}).get("login") == owner
                        and pr_repo.get("name") == repo
                    ):
                        pr_number = issue.get("number")
                        if pr_number:
                            try:
                                for pr_commit in client.get_paginated(
                                    f"/repos/{owner}/{repo}/pulls/{pr_number}/commits"
                                ):
                                    commit_sha = pr_commit.get("sha", "")
                                    commit_date = (
                                        pr_commit.get("commit", {})
                                        .get("committer", {})
                                        .get("date", "")
                                    )
                                    if commit_sha:
                                        _, branches = verify_commit_exists(
                                            client, owner, repo, commit_sha
                                        )
                                        all_commits.append(
                                            CommitInfo(
                                                sha=commit_sha,
                                                date=commit_date,
                                                branches=branches,
                                            )
                                        )
                            except Exception:
                                pass
        except Exception as e:
            logger.warning(f"Failed to check related PRs: {e}")

    # Filter out excluded commits
    all_commits = [
        c
        for c in all_commits
        if not any(c.sha.startswith(exc) for exc in excluded_hashes)
        and c.sha not in excluded_hashes
    ]

    # Sort commits by date
    all_commits.sort(key=lambda x: x.date)

    # Remove duplicates while preserving order
    seen: set[str] = set()
    unique_commits: list[CommitInfo] = []
    for commit in all_commits:
        if commit.sha not in seen:
            seen.add(commit.sha)
            unique_commits.append(commit)

    # Verify commits and collect branch info
    verified_commits_with_branches: list[tuple[str, list[str]]] = []
    for commit in unique_commits:
        verified_sha, branches = verify_commit_exists(client, owner, repo, commit.sha)
        if verified_sha:
            verified_commits_with_branches.append((verified_sha, branches or commit.branches))

    # Filter commits to same branch
    if verified_commits_with_branches:
        sorted_shas = filter_commits_by_branch(
            client, owner, repo, verified_commits_with_branches
        )
    else:
        sorted_shas = []

    # Remove duplicates while preserving order
    sorted_shas = list(dict.fromkeys(sorted_shas))

    # Get latest and base commits
    latest_commit = sorted_shas[-1] if sorted_shas else ""
    base_commit = get_base_commit(
        client, owner, repo, sorted_shas, manual_base_commit
    )

    return FetchedCommits(
        commits=sorted_shas,
        latest_commit=latest_commit,
        base_commit=base_commit,
    )
