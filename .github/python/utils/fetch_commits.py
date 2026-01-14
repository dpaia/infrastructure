#!/usr/bin/env python3

# Simple test to check if the script is being executed
print("SCRIPT_EXECUTION_TEST: fetch_commits.py is being executed")

import os
import re
import sys
import json
import subprocess

"""
Script to fetch commits related to a GitHub issue.

This script extracts all commits linked to a specific GitHub issue through:
- GitHub's Timeline API to find referenced commits
- Manually linked commits in the issue description (using regex patterns)
- Manually linked commits in issue comments
- Related pull requests if no direct commits are found

It verifies each commit exists in the repository, gets commit dates for sorting,
and outputs the latest commit hash, base commit hash, and all commits as a JSON array.
"""

from generate_data import *

def verify_commit_exists(owner, repo_name, commit_hash):
    """
    Verify if a commit exists in the repository by checking if it's reachable from any branch.
    First tries branches-where-head API, then falls back to checking all branches if needed.

    Args:
        owner (str): GitHub organization name
        repo_name (str): GitHub repository name
        commit_hash (str): The commit hash to verify

    Returns:
        tuple: (full_commit_hash, branches) where branches is a list of branch names containing this commit
               Returns ("", []) if commit doesn't exist or isn't reachable from any branch
    """
    if not commit_hash:
        return "", []

    # First, try to get the commit directly to verify it exists
    cmd = [
        'gh', 'api',
        f'repos/{owner}/{repo_name}/commits/{commit_hash}',
        '--jq', '.sha'
    ]

    result = run_subprocess(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return "", []  # Commit doesn't exist

    full_commit_hash = result.stdout.strip()

    # Step 1: Check if commit is the head of any branch using branches-where-head API
    print(f"Checking if commit {commit_hash} is head of any branch...")
    cmd = [
        'gh', 'api',
        f'repos/{owner}/{repo_name}/commits/{commit_hash}/branches-where-head',
        '--jq', '.[].name'
    ]

    result = run_subprocess(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0 and result.stdout.strip():
        branches_where_head = result.stdout.strip().split('\n')
        print(f"Commit {commit_hash} is head of branches: {', '.join(branches_where_head)}")
        return full_commit_hash, branches_where_head

    print(f"Commit {commit_hash} is not head of any branch, checking all branches...")

    # Step 2: If not head of any branch, check all branches with pagination (100 per page)
    cmd = [
        'gh', 'api',
        '-H', 'X-GitHub-Api-Version: 2022-11-28',
        f'repos/{owner}/{repo_name}/branches?per_page=100',
        '--paginate',
        '--jq', '.[].name'
    ]

    result = run_subprocess(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"Warning: Could not fetch branches for repository {owner}/{repo_name}")
        return full_commit_hash, []  # If we can't get branches but commit exists, assume it's valid

    branches = result.stdout.strip().split('\n') if result.stdout.strip() else []

    # Check if commit is reachable from any branch and collect all branches that contain it
    containing_branches = []
    for branch in branches:
        if not branch:
            continue

        # URL encode branch name to handle special characters like #
        import urllib.parse
        encoded_branch = urllib.parse.quote(branch, safe='')

        cmd = [
            'gh', 'api',
            '-H', 'X-GitHub-Api-Version: 2022-11-28',
            f'repos/{owner}/{repo_name}/compare/{commit_hash}...{encoded_branch}',
            '--jq', '.status'
        ]

        result = run_subprocess(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            status = result.stdout.strip()
            # If status is "ahead" or "identical", the commit is reachable from this branch
            if status in ["ahead", "identical"]:
                containing_branches.append(branch)

    if containing_branches:
        print(f"Commit {commit_hash} found in branches: {', '.join(containing_branches)}")
        return full_commit_hash, containing_branches

    print(f"Warning: Commit {commit_hash} exists but is not reachable from any branch")
    return "", []

def filter_commits_by_branch(commits_with_branches, owner, repo_name):
    """
    Filters commits to ensure they all belong to the same branch.
    Prioritizes the default branch (main/master) if available.

    Args:
        commits_with_branches (list): List of tuples (commit_sha, branches_list)
        owner (str): GitHub organization name
        repo_name (str): Repository name

    Returns:
        list: Filtered list of commit SHAs that all belong to the same branch
    """
    if len(commits_with_branches) <= 1:
        return [c[0] for c in commits_with_branches]

    print(f"Filtering {len(commits_with_branches)} commits to ensure they belong to the same branch...", file=sys.stderr)

    # Get the default branch
    cmd = [
        'gh', 'api',
        f'repos/{owner}/{repo_name}',
        '--jq', '.default_branch'
    ]
    result = run_subprocess(cmd, capture_output=True, text=True, check=False)
    default_branch = result.stdout.strip() if result.returncode == 0 else "main"
    print(f"Default branch: {default_branch}", file=sys.stderr)

    # Find the branch that contains the most commits
    branch_commit_count = {}
    for commit_sha, branches in commits_with_branches:
        for branch in branches:
            branch_commit_count[branch] = branch_commit_count.get(branch, 0) + 1

    # Prefer default branch if it contains any commits, otherwise use the branch with most commits
    target_branch = None
    if default_branch in branch_commit_count:
        target_branch = default_branch
        print(f"Using default branch '{target_branch}' which contains {branch_commit_count[target_branch]} commits", file=sys.stderr)
    elif branch_commit_count:
        target_branch = max(branch_commit_count, key=branch_commit_count.get)
        print(f"Using branch '{target_branch}' which contains {branch_commit_count[target_branch]} commits", file=sys.stderr)
    else:
        print("Warning: No branch found for commits, returning all commits", file=sys.stderr)
        return [c[0] for c in commits_with_branches]

    # Filter commits that belong to the target branch
    filtered = []
    for commit_sha, branches in commits_with_branches:
        if target_branch in branches:
            filtered.append(commit_sha)
        else:
            print(f"Excluding commit {commit_sha[:7]} - not in branch '{target_branch}' (found in: {', '.join(branches)})", file=sys.stderr)

    print(f"Filtered commits to {len(filtered)} commits from branch '{target_branch}'", file=sys.stderr)
    return filtered

def filter_best_commits(verified_commits, owner, repo_name):
    """
    Filters commits to keep only the "best" ones for patch application.

    Uses ancestor-descendant relationship check: if commit B is a descendant
    of commit A (B contains all changes from A), keeps only B to avoid
    duplicate patches.

    Args:
        verified_commits (list): List of verified commit SHAs
        owner (str): GitHub organization name
        repo_name (str): Repository name

    Returns:
        list: Filtered list of commits
    """
    if len(verified_commits) <= 1:
        return verified_commits

    print(f"Filtering {len(verified_commits)} commits to avoid patch conflicts...", file=sys.stderr)

    # Check if commits are sequential (ancestor-descendant relationship)
    # If commit B is a descendant of commit A, keep only B
    filtered = []

    for i, commit in enumerate(verified_commits):
        is_ancestor_of_later = False

        # Check if this commit is an ancestor of any later commits
        for j in range(i + 1, len(verified_commits)):
            later_commit = verified_commits[j]

            # Check if commit is ancestor of later_commit using compare API
            cmd = [
                'gh', 'api',
                f'repos/{owner}/{repo_name}/compare/{commit}...{later_commit}',
                '--jq', '.status'
            ]

            result = run_subprocess(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                status = result.stdout.strip()
                # If status = "ahead", later_commit contains all changes from commit
                if status == "ahead":
                    print(f"Commit {commit[:7]} is ancestor of {later_commit[:7]}, keeping only descendant", file=sys.stderr)
                    is_ancestor_of_later = True
                    break

        if not is_ancestor_of_later:
            filtered.append(commit)

    if len(filtered) < len(verified_commits):
        print(f"Filtered out {len(verified_commits) - len(filtered)} ancestor commits", file=sys.stderr)
        print(f"Remaining commits after filtering: {[c[:7] for c in filtered]}", file=sys.stderr)
    else:
        print(f"No ancestor commits found, keeping all {len(verified_commits)} commits", file=sys.stderr)

    return filtered

def fetch_commits(organization, repository, issue_number, github_token=None):
    """
    Fetch commits related to a GitHub issue.

    Args:
        organization (str): GitHub organization name
        repository (str): GitHub repository name
        issue_number (str): Issue number
        github_token (str, optional): GitHub token for API access. Defaults to None.

    Returns:
        dict: Dictionary containing:
            - commit_hash: The hash of the latest commit related to the issue
            - base_commit_hash: The hash of the parent commit (base commit)
            - commits: Array of commits linked to the issue, sorted by date (newest last)
    """
    # Set GitHub token if provided
    if github_token:
        os.environ['GH_TOKEN'] = github_token

    owner = organization
    repo_name = repository

    print(f"Fetching commits linked to issue #{issue_number}...")

    # Use GitHub's Timeline API to find linked commits and cross-referenced PRs
    # Paginate through all timeline events since API returns only 30 by default
    print("Fetching timeline events...")
    all_timeline_events = []
    per_page = 100
    max_pages = 100  # Safety limit to prevent infinite loops (10,000 events max)

    for page in range(1, max_pages + 1):
        print(f"Fetching timeline page {page}...")
        cmd = [
            'gh', 'api',
            '-H', 'X-GitHub-Api-Version: 2022-11-28',
            f'repos/{owner}/{repo_name}/issues/{issue_number}/timeline?per_page={per_page}&page={page}'
        ]

        result = run_subprocess(cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            print(f"Error fetching timeline page {page}, stopping pagination")
            break

        page_results = result.stdout.strip()

        # If no results on this page, we've reached the end
        if not page_results:
            print(f"No more timeline events found at page {page}")
            break

        try:
            page_events = json.loads(page_results)
            all_timeline_events.extend(page_events)
            print(f"Fetched {len(page_events)} timeline events on page {page}")
        except json.JSONDecodeError as e:
            print(f"Error parsing timeline events on page {page}: {e}")
            break

    print(f"Total timeline events fetched: {len(all_timeline_events)}")

    # Extract referenced commits from timeline events
    linked_commits_with_dates = ""
    referenced_commit_count = 0
    for event in all_timeline_events:
        if event.get('event') == 'referenced' and event.get('commit_id'):
            commit_data = json.dumps({'sha': event['commit_id'], 'date': event['created_at']})
            if linked_commits_with_dates:
                linked_commits_with_dates += "\n" + commit_data
            else:
                linked_commits_with_dates = commit_data
            referenced_commit_count += 1

    print(f"Found {referenced_commit_count} referenced commits in timeline")

    # Initialize an empty array for all commits and excluded commit hashes
    all_commits = []
    excluded_commit_hashes = []

    # Check for manually linked commits in the issue description first
    print("Checking issue description for manually linked commits...")
    print("Nikita Morozov debug info:")
    print(f"{owner = }, {repo_name = }, {issue_number = } ")
    cmd = [
        'gh', 'api',
        f'repos/{owner}/{repo_name}/issues/{issue_number}',
        '--jq', '.body'
    ]
    print(f"{cmd = }")

    result = run_subprocess(cmd, capture_output=True, text=True, check=False)
    print(f"{result = }")
    issue_body = result.stdout.strip() if result.returncode == 0 else ""
    print(f"{issue_body = }")

    if issue_body:
        print("Processing issue description for commit references...")

        # First, check for excluded commits
        excluded_pattern = re.findall(r'[Ee]xcluded\s+([0-9a-f]{7,40})', issue_body)
        if excluded_pattern:
            for commit_hash in excluded_pattern:
                print(f"Found excluded commit in issue description: {commit_hash}")
                excluded_commit_hashes.append(commit_hash)

        # Extract commit hashes using multiple regex patterns
        commit_pattern_1 = re.findall(r'(?:[Rr]elated\s+)?[Cc]ommit:?\s+([0-9a-f]{40})', issue_body)
        commit_pattern_2 = re.findall(r'\b([0-9a-f]{40})\b', issue_body)

        # Combine patterns but prioritize specific mentions
        commit_hashes = set()
        if commit_pattern_1:
            commit_hashes.update(commit_pattern_1)
        if commit_pattern_2:
            commit_hashes.update(commit_pattern_2)

        if commit_hashes:
            for commit_hash in commit_hashes:
                print(f"Found potential commit hash in issue description: {commit_hash}")

                # Verify this commit exists in the repository
                commit_exists, branches = verify_commit_exists(owner, repo_name, commit_hash)

                if commit_exists:
                    # Get commit date for sorting
                    cmd = [
                        'gh', 'api',
                        f'repos/{owner}/{repo_name}/commits/{commit_hash}',
                        '--jq', '.commit.committer.date'
                    ]

                    result = run_subprocess(cmd, capture_output=True, text=True, check=False)
                    commit_date = result.stdout.strip() if result.returncode == 0 else ""

                    if commit_date:
                        print(f"Adding verified commit from issue description: {commit_hash} ({commit_date})")
                        all_commits.append({"sha": commit_hash, "date": commit_date, "branches": branches})
                else:
                    print(f"Commit {commit_hash} from issue description does not exist in this repository, skipping")

    # Check for manually linked commits and excluded commits in issue comments
    print("Checking issue comments for manually linked commits...")
    cmd = [
        'gh', 'api',
        f'repos/{owner}/{repo_name}/issues/{issue_number}/comments',
        '--jq', '.[].body'
    ]

    result = run_subprocess(cmd, capture_output=True, text=True, check=False)
    comments = result.stdout.strip() if result.returncode == 0 else ""

    # Track excluded commits and manual base commit
    excluded_commits = set()
    manual_base_commit = ""

    if comments:
        print("Processing issue comments for commit references...")
        for comment in comments.split('\n'):
            if not comment:
                continue

            # Check for manual base commit first
            # Pattern: "Base commit: <hash>"
            base_pattern = re.findall(r'[Bb]ase\s+[Cc]ommit:?\s+([0-9a-f]{7,40})', comment)

            if base_pattern:
                for commit_hash in base_pattern:
                    print(f"Found manual base commit in comment: {commit_hash}")

                    # Verify and get full hash
                    commit_exists = verify_commit_exists(owner, repo_name, commit_hash)
                    if commit_exists:
                        manual_base_commit = commit_exists
                        print(f"Will use manual base commit: {commit_exists[:7]}")
                        break  # Use first valid base commit found

            # Check for excluded commits
            # Pattern: "Excluded <hash>" or "Exclude <hash>"
            exclude_pattern = re.findall(r'[Ee]xclude[d]?\s+([0-9a-f]{7,40})', comment)

            if exclude_pattern:
                for commit_hash in exclude_pattern:
                    print(f"Found excluded commit in comment: {commit_hash}")

                    # Verify and get full hash
                    commit_exists, _ = verify_commit_exists(owner, repo_name, commit_hash)
                    if commit_exists:
                        excluded_commits.add(commit_exists)
                        print(f"Will exclude commit: {commit_exists[:7]}")

            # First, check for excluded commits
            excluded_pattern = re.findall(r'[Ee]xcluded\s+([0-9a-f]{7,40})', comment)
            if excluded_pattern:
                for commit_hash in excluded_pattern:
                    print(f"Found excluded commit in comment: {commit_hash}")
                    excluded_commit_hashes.append(commit_hash)

            # Extract commit hashes using multiple regex patterns to catch different formats
            # Pattern 1: Common formats like "Related commit: HASH", "Commit: HASH", etc.
            commit_pattern_1 = re.findall(r'(?:[Rr]elated\s+)?[Cc]ommit:?\s+([0-9a-f]{40})', comment)
            # Pattern 2: Stand-alone SHA format (just the hash with 40 characters)
            commit_pattern_2 = re.findall(r'\b([0-9a-f]{40})\b', comment)
            # Pattern 3: Format with SHA hash in GitHub UI style (7-40 characters)
            commit_pattern_3 = re.findall(r'\b([0-9a-f]{7,40})\b', comment)

            # Combine all patterns but prioritize longer matches (40 char hashes)
            commit_hashes = set()
            if commit_pattern_1:
                commit_hashes.update(commit_pattern_1)
            if commit_pattern_2:
                commit_hashes.update(commit_pattern_2)
            if not commit_pattern_1 and not commit_pattern_2 and commit_pattern_3:
                # Only use pattern 3 if we didn't find any 40-char hashes
                commit_hashes.update(commit_pattern_3)

            if commit_hashes:
                for commit_hash in commit_hashes:
                    # Skip if this commit is in excluded list
                    if any(commit_hash in exc for exc in excluded_commits):
                        print(f"Skipping excluded commit: {commit_hash}")
                        continue

                    print(f"Found potential commit hash in comment: {commit_hash}")

                    # Verify this commit exists in the repository
                    commit_exists, branches = verify_commit_exists(owner, repo_name, commit_hash)

                    if commit_exists:
                        # Skip if full hash is excluded
                        if commit_exists in excluded_commits:
                            print(f"Skipping excluded commit: {commit_exists[:7]}")
                            continue

                        # We have a valid commit, now get its full hash and date
                        full_commit_hash = commit_exists
                        cmd = [
                            'gh', 'api',
                            f'repos/{owner}/{repo_name}/commits/{full_commit_hash}',
                            '--jq', '.commit.committer.date'
                        ]

                        result = run_subprocess(cmd, capture_output=True, text=True, check=False)
                        commit_date = result.stdout.strip() if result.returncode == 0 else ""

                        if commit_date:
                            print(f"Adding verified commit from comment: {full_commit_hash} ({commit_date})")
                            all_commits.append({"sha": full_commit_hash, "date": commit_date, "branches": branches})
                        else:
                            print(f"Could not get date for commit {full_commit_hash}, skipping")
                    else:
                        print(f"Commit {commit_hash} does not exist in this repository, skipping")

    if linked_commits_with_dates:
        print("Found linked commits in timeline")
        # Convert to array of objects with sha and date
        for commit_data in linked_commits_with_dates.split('\n'):
            if commit_data:
                try:
                    commit_obj = json.loads(commit_data)
                    # Verify commit and get branches
                    commit_sha = commit_obj.get('sha', '')
                    if commit_sha:
                        _, branches = verify_commit_exists(owner, repo_name, commit_sha)
                        commit_obj['branches'] = branches
                    all_commits.append(commit_obj)
                except json.JSONDecodeError:
                    print(f"Error parsing commit data: {commit_data}")
    else:
        print(f"No commits found linked to issue #{issue_number} through GitHub references")

        # Try to check for cross-referenced PRs that might contain commits
        # Extract from already-fetched timeline events
        print("Checking for related pull requests in timeline events...")
        related_pr_numbers = []
        for event in all_timeline_events:
            if (event.get('event') == 'cross-referenced' and
                event.get('source', {}).get('issue', {}).get('pull_request') is not None):
                source = event.get('source', {})
                issue = source.get('issue', {})
                repo = issue.get('repository', {})
                if (repo.get('owner', {}).get('login') == owner and
                    repo.get('name') == repo_name):
                    pr_number = issue.get('number')
                    if pr_number:
                        related_pr_numbers.append(str(pr_number))

        related_prs = "\n".join(related_pr_numbers) if related_pr_numbers else ""

        if related_prs:
            print(f"Found related PRs: {related_prs}")
            # Get the most recent PR
            recent_pr = related_prs.split('\n')[0]
            print(f"Checking commits from PR #{recent_pr}...")

            cmd = [
                'gh', 'api',
                f'repos/{owner}/{repo_name}/pulls/{recent_pr}/commits',
                '--jq', '.[] | {sha: .sha, date: .commit.committer.date}'
            ]

            result = run_subprocess(cmd, capture_output=True, text=True, check=False)
            pr_commits_with_dates = result.stdout.strip() if result.returncode == 0 else ""

            if pr_commits_with_dates:
                print(f"Found commits in PR #{recent_pr}")
                # Add PR commits to all_commits array
                for commit_data in pr_commits_with_dates.split('\n'):
                    if commit_data:
                        try:
                            commit_obj = json.loads(commit_data)
                            # Verify commit and get branches
                            commit_sha = commit_obj.get('sha', '')
                            if commit_sha:
                                _, branches = verify_commit_exists(owner, repo_name, commit_sha)
                                commit_obj['branches'] = branches
                            all_commits.append(commit_obj)
                        except json.JSONDecodeError:
                            print(f"Error parsing commit data: {commit_data}")

    # Filter out excluded commits before processing
    if excluded_commit_hashes:
        print(f"Filtering out {len(excluded_commit_hashes)} excluded commits: {excluded_commit_hashes}")
        # Filter out commits that match any excluded hash (support both short and full hashes)
        all_commits = [
            commit for commit in all_commits
            if not any(commit.get('sha', '').startswith(excluded_hash) for excluded_hash in excluded_commit_hashes)
        ]
        print(f"Remaining commits after filtering: {len(all_commits)}")

    # Sort commits by date and create a JSON array
    if all_commits:
        print(f"Sorting {len(all_commits)} commits by date...")

        # Sort commits by date
        sorted_commits = sorted(all_commits, key=lambda x: x.get('date', ''))

        # Extract just the SHA values
        sorted_commit_shas = [commit.get('sha', '') for commit in sorted_commits]

        # Verify all commits exist in repository and collect branch info
        print(f"Verifying all {len(sorted_commit_shas)} commits exist in repository...")
        verified_commits_with_branches = []
        for commit_sha in sorted_commit_shas:
            # Skip excluded commits
            if commit_sha in excluded_commits:
                print(f"Skipping excluded commit: {commit_sha[:7]}")
                continue

            if commit_sha:
                verified_sha, branches = verify_commit_exists(owner, repo_name, commit_sha)
                if verified_sha:
                    verified_commits_with_branches.append((verified_sha, branches))
                else:
                    print(f"Warning: Commit {commit_sha} does not exist in repository, removing from list")

        if verified_commits_with_branches:
            # Filter commits to ensure they all belong to the same branch
            sorted_commit_shas = filter_commits_by_branch(verified_commits_with_branches, owner, repo_name)

            # Remove duplicates while preserving order
            sorted_commit_shas = list(dict.fromkeys(sorted_commit_shas))

            # Apply filtering to avoid patch conflicts from ancestor commits
            # Disabled: We want ALL commits from the task branch, not just the final one
            # if len(sorted_commit_shas) > 1:
            #     sorted_commit_shas = filter_best_commits(sorted_commit_shas, owner, repo_name)
        else:
            print("Warning: No verified commits found in repository, using all commits")

        print(f"Verified commits: {sorted_commit_shas}")

        # Get the latest commit (last in the sorted array)
        latest_commit = sorted_commit_shas[-1] if sorted_commit_shas else ""
        print(f"Using most recent commit: {latest_commit}")
    else:
        print(f"No commits found for issue #{issue_number}")
        sorted_commit_shas = []
        latest_commit = ""

    # Get the commit before the earliest commit (base commit)
    base_commit = ""

    # Check if we have a manual base commit from comments
    if manual_base_commit:
        print(f"Using manual base commit from comment: {manual_base_commit}")
        base_commit = manual_base_commit
    elif sorted_commit_shas:
        earliest_commit = sorted_commit_shas[0]  # First commit in sorted array (earliest by date)
        print(f"Fetching base commit (parent of earliest commit: {earliest_commit})...")
        cmd = [
            'gh', 'api',
            f'repos/{owner}/{repo_name}/commits/{earliest_commit}',
            '--jq', '.parents[0].sha'
        ]

        result = run_subprocess(cmd, capture_output=True, text=True, check=False)
        base_commit = result.stdout.strip() if result.returncode == 0 else ""

        if base_commit:
            # Verify base commit exists
            verified_base, _ = verify_commit_exists(owner, repo_name, base_commit)
            if verified_base:
                base_commit = verified_base
                print(f"Base commit: {base_commit}")
            else:
                print(f"Base commit {base_commit} does not exist in repository, using older repository commit")
                base_commit = ""

        # If base commit isn't valid, try to get an older repository commit
        if not base_commit:
            print("Finding older repository commit...")
            cmd = [
                'gh', 'api',
                f'repos/{owner}/{repo_name}/commits',
                '--jq', '.[1].sha'
            ]

            result = run_subprocess(cmd, capture_output=True, text=True, check=False)
            potential_base_commit = result.stdout.strip() if result.returncode == 0 else ""

            # Verify this commit exists too
            if potential_base_commit:
                verified_potential, _ = verify_commit_exists(owner, repo_name, potential_base_commit)
                if verified_potential:
                    base_commit = verified_potential
                    print(f"Using older repository commit: {base_commit}")
                else:
                    print(f"Warning: Could not find a valid base commit")
            else:
                print(f"Warning: Could not find a valid base commit")

    return {
        "commit_hash": latest_commit,
        "base_commit_hash": base_commit,
        "commits": sorted_commit_shas
    }



def main():
    """Main function to run the script from command line."""
    print("DEBUG: Starting main function")
    if len(sys.argv) < 4:
        print("Usage: fetch_commits.py <organization> <repository> <issue_number> [github_token]")
        sys.exit(1)

    organization = sys.argv[1]
    repository = sys.argv[2]
    issue_number = sys.argv[3]
    github_token = sys.argv[4] if len(sys.argv) > 4 else os.environ.get('GH_TOKEN')

    print(f"DEBUG: Arguments - org: {organization}, repo: {repository}, issue: {issue_number}, token: {'set' if github_token else 'not set'}")

    try:
        print("DEBUG: Calling fetch_commits function")
        result = fetch_commits(organization, repository, issue_number, github_token)
        print(f"DEBUG: fetch_commits returned: {result}")
    except Exception as e:
        print(f"ERROR: Exception in fetch_commits: {str(e)}")
        import traceback
        print(traceback.format_exc())
        sys.exit(1)

    # Output the results in GitHub Actions format
    # Print the results to stdout for visibility in logs
    print(f"RESULT: commit_hash={result['commit_hash']}")
    print(f"RESULT: base_commit_hash={result['base_commit_hash']}")
    print(f"RESULT: commits={json.dumps(result['commits'])}")

    # Output for GitHub Actions
    # Check if GITHUB_OUTPUT environment variable exists (GitHub Actions environment)
    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        # Current recommended way to set outputs in GitHub Actions
        with open(github_output, 'a') as f:
            f.write(f"commit_hash={result['commit_hash']}\n")
            f.write(f"base_commit_hash={result['base_commit_hash']}\n")
            f.write(f"commits={json.dumps(result['commits'])}\n")
    else:
        # Fallback for local testing or older GitHub Actions
        print(f"commit_hash={result['commit_hash']}")
        print(f"base_commit_hash={result['base_commit_hash']}")
        print(f"commits={json.dumps(result['commits'])}")


# Call the main function when the script is executed directly
if __name__ == "__main__":
    print("DEBUG: __name__ == '__main__', calling main()")
    main()
