#!/usr/bin/env python3

# Simple test to check if the script is being executed
print("SCRIPT_EXECUTION_TEST: fetch_commits.py is being executed")

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
    
    # Use GitHub's Timeline API to find linked commits with their dates
    print("Fetching commits with dates from timeline...")
    cmd = [
        'gh', 'api', 
        f'repos/{owner}/{repo_name}/issues/{issue_number}/timeline',
        '--jq', '.[] | select(.event == "referenced" and .commit_id != null) | {sha: .commit_id, date: .created_at}'
    ]
    
    result = run_subprocess(cmd, capture_output=True, text=True, check=False)
    linked_commits_with_dates = result.stdout.strip() if result.returncode == 0 else ""
    
    # Initialize an empty array for all commits
    all_commits = []
    
    # Check for manually linked commits in the issue description first
    print("Checking issue description for manually linked commits...")
    cmd = [
        'gh', 'api',
        f'repos/{owner}/{repo_name}/issues/{issue_number}',
        '--jq', '.body'
    ]
    
    result = run_subprocess(cmd, capture_output=True, text=True, check=False)
    issue_body = result.stdout.strip() if result.returncode == 0 else ""
    
    if issue_body:
        print("Processing issue description for commit references...")
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
                cmd = [
                    'gh', 'api',
                    f'repos/{owner}/{repo_name}/commits/{commit_hash}',
                    '--jq', '.sha'
                ]
                
                result = run_subprocess(cmd, capture_output=True, text=True, check=False)
                commit_exists = result.stdout.strip() if result.returncode == 0 else ""
                
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
                        all_commits.append({"sha": commit_hash, "date": commit_date})
                else:
                    print(f"Commit {commit_hash} from issue description does not exist in this repository, skipping")
    
    # Check for manually linked commits in issue comments
    print("Checking issue comments for manually linked commits...")
    cmd = [
        'gh', 'api',
        f'repos/{owner}/{repo_name}/issues/{issue_number}/comments',
        '--jq', '.[].body'
    ]
    
    result = run_subprocess(cmd, capture_output=True, text=True, check=False)
    comments = result.stdout.strip() if result.returncode == 0 else ""
    
    if comments:
        print("Processing issue comments for commit references...")
        for comment in comments.split('\n'):
            if not comment:
                continue
                
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
                    print(f"Found potential commit hash in comment: {commit_hash}")
                    
                    # Verify this commit exists in the repository
                    cmd = [
                        'gh', 'api',
                        f'repos/{owner}/{repo_name}/commits/{commit_hash}',
                        '--jq', '.sha'
                    ]
                    
                    result = run_subprocess(cmd, capture_output=True, text=True, check=False)
                    commit_exists = result.stdout.strip() if result.returncode == 0 else ""
                    
                    if commit_exists:
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
                            all_commits.append({"sha": full_commit_hash, "date": commit_date})
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
                    all_commits.append(commit_obj)
                except json.JSONDecodeError:
                    print(f"Error parsing commit data: {commit_data}")
    else:
        print(f"No commits found linked to issue #{issue_number} through GitHub references")
        
        # Try to check for cross-referenced PRs that might contain commits
        print("Checking for related pull requests...")
        cmd = [
            'gh', 'api',
            f'repos/{owner}/{repo_name}/issues/{issue_number}/timeline',
            '--jq', '.[] | select(.event == "cross-referenced" and .source.issue.pull_request != null and .source.issue.repository.owner.login == "' + owner + '" and .source.issue.repository.name == "' + repo_name + '") | .source.issue.number'
        ]
        
        result = run_subprocess(cmd, capture_output=True, text=True, check=False)
        related_prs = result.stdout.strip() if result.returncode == 0 else ""
        
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
                            all_commits.append(commit_obj)
                        except json.JSONDecodeError:
                            print(f"Error parsing commit data: {commit_data}")
    
    # Sort commits by date and create a JSON array
    if all_commits:
        print(f"Sorting {len(all_commits)} commits by date...")
        
        # Sort commits by date
        sorted_commits = sorted(all_commits, key=lambda x: x.get('date', ''))
        
        # Extract just the SHA values
        sorted_commit_shas = [commit.get('sha', '') for commit in sorted_commits]
        
        print(f"Sorted commits: {sorted_commit_shas}")
        
        # Get the latest commit (last in the sorted array)
        latest_commit = sorted_commit_shas[-1] if sorted_commit_shas else ""
        print(f"Using most recent commit: {latest_commit}")
    else:
        print(f"No commits found for issue #{issue_number}")
        sorted_commit_shas = []
        latest_commit = ""
    
    # Get the commit before the latest commit (base commit)
    base_commit = ""
    if latest_commit:
        print("Fetching base commit (parent of latest commit)...")
        cmd = [
            'gh', 'api',
            f'repos/{owner}/{repo_name}/commits/{latest_commit}',
            '--jq', '.parents[0].sha'
        ]
        
        result = run_subprocess(cmd, capture_output=True, text=True, check=False)
        base_commit = result.stdout.strip() if result.returncode == 0 else ""
        
        if base_commit:
            print(f"Base commit: {base_commit}")
        else:
            print("No parent commit found, using older repository commit")
            cmd = [
                'gh', 'api',
                f'repos/{owner}/{repo_name}/commits',
                '--jq', '.[1].sha'
            ]
            
            result = run_subprocess(cmd, capture_output=True, text=True, check=False)
            base_commit = result.stdout.strip() if result.returncode == 0 else ""
            print(f"Older repository commit: {base_commit}")
    
    return {
        "commit_hash": latest_commit,
        "base_commit_hash": base_commit,
        "commits": sorted_commit_shas
    }