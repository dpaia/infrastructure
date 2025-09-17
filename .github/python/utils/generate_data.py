#!/usr/bin/env python3
import importlib
import json
import os
import re
import sys

# Try to import unidiff, fall back to None if not available
try:
    from unidiff import PatchSet
    UNIDIFF_AVAILABLE = True
except ImportError:
    PatchSet = None
    UNIDIFF_AVAILABLE = False


# Function to determine if a file is a test file based on its path
def is_test_file(file_path):
    """
    Determines if a file is a test file based on its path.
    
    Args:
        file_path (str): The path of the file to check
        
    Returns:
        bool: True if the file is a test file, False otherwise
    """
    # Common patterns for test files
    test_patterns = [
        r'/test/', r'/tests/',                  # Common test directories
        r'_test\.', r'Test\.', r'Tests\.',      # Common test file naming patterns
        r'/src/test/', r'/main/test/',          # Java/Maven test directories
        r'/spec/', r'/specs/',                  # Ruby/JS spec directories
        r'_spec\.', r'Spec\.',                  # Ruby/JS spec file naming patterns
        r'__tests__', r'__test__',              # JS/TS test directories
        r'_test_', r'test_'                     # Python test file naming patterns
    ]
    
    # Check if any test pattern matches the file path
    for pattern in test_patterns:
        if re.search(pattern, file_path, re.IGNORECASE):
            return True
    
    return False

# Create a wrapper function for subprocess.run that won't be affected by mocks
def run_subprocess(cmd, **kwargs):
    # Get the real subprocess module, even if it's been mocked
    real_subprocess = importlib.import_module('subprocess')
    return real_subprocess.run(cmd, **kwargs)

# Function to generate instance_id using organization and repository name
def generate_instance_id(organization, repository, latest_commit):
    short_hash = latest_commit[:8] if latest_commit else 'unknown'
    org_for_id = organization.replace('-', '__')
    repo_for_id = repository.replace('-', '__')
    return f"{org_for_id}__{repo_for_id}-{short_hash}"

# Function to fetch problem statement from GitHub issue
def fetch_problem_statement(organization, repository, issue_number):
    default_title = ""
    default_body = ""

    try:
        if issue_number != 'unknown' and os.environ.get('GH_TOKEN', ''):
            # Use GitHub CLI to fetch issue title and body
            cmd = [
                'gh', 'api', 
                f'repos/{organization}/{repository}/issues/{issue_number}',
                '--jq', '{title: .title, body: .body}'
            ]

            result = run_subprocess(cmd, capture_output=True, text=True, check=True)
            issue_data = json.loads(result.stdout.strip())
            issue_title = issue_data.get('title', '').strip()
            issue_body = issue_data.get('body', '').strip()

            if issue_title or issue_body:
                print(f"Successfully fetched issue title and body for issue #{issue_number}", file=sys.stderr)
                return {
                    'title': issue_title,
                    'body': issue_body
                }
            else:
                print(f"Issue #{issue_number} has no title or body, using empty problem statement", file=sys.stderr)
                return {
                    'title': default_title,
                    'body': default_body
                }
        else:
            print("Missing issue number or GitHub token, using empty problem statement", file=sys.stderr)
            return {
                'title': default_title,
                'body': default_body
            }
    except Exception as e:
        print(f"Error fetching issue title and body: {e}", file=sys.stderr)
        print("Using empty problem statement", file=sys.stderr)
        return {
            'title': default_title,
            'body': default_body
        }

# Function to fetch commit IDs for a ticket
def fetch_commit_ids(organization, repository, issue_number):
    """
    Fetches commit IDs linked to a specific issue.
    
    Args:
        organization (str): GitHub organization name
        repository (str): GitHub repository name
        issue_number (str): Issue number
        
    Returns:
        list: List of commit IDs linked to the issue
    """
    try:
        # Check for test environment variable
        test_commit_ids = os.environ.get('TEST_COMMIT_IDS', '')
        if test_commit_ids:
            print(f"Using test commit IDs from environment variable", file=sys.stderr)
            return test_commit_ids.split(',')
            
        if issue_number == 'unknown' or not os.environ.get('GH_TOKEN', ''):
            print("Missing issue number or GitHub token, skipping commit ID fetch", file=sys.stderr)
            return []

        print(f"Fetching linked commits for issue #{issue_number} in {organization}/{repository}...", file=sys.stderr)

        # First, get directly linked commit IDs
        cmd = [
            'gh', 'api', 
            f'repos/{organization}/{repository}/issues/{issue_number}/timeline',
            '--jq', '.[] | select(.event == "referenced" and .commit_id != null) | .commit_id'
        ]

        print(f"Executing command: {' '.join(cmd)}", file=sys.stderr)
        result = run_subprocess(cmd, capture_output=True, text=True, check=True)
        commit_ids = result.stdout.strip().split('\n')
        commit_ids = [commit_id for commit_id in commit_ids if commit_id]

        if commit_ids:
            print(f"Found {len(commit_ids)} directly linked commits: {', '.join(commit_ids)}", file=sys.stderr)
        else:
            print("No directly linked commits found, checking PRs...", file=sys.stderr)

            # Try to get commits from PRs
            cmd = [
                'gh', 'api',
                f'repos/{organization}/{repository}/issues/{issue_number}/timeline',
                '--jq', '.[] | select(.event == "cross-referenced" and .source.issue.pull_request != null) | .source.issue.number'
            ]

            print(f"Executing command: {' '.join(cmd)}", file=sys.stderr)
            result = run_subprocess(cmd, capture_output=True, text=True, check=True)
            pr_numbers = result.stdout.strip().split('\n')
            pr_numbers = [pr for pr in pr_numbers if pr]

            if pr_numbers:
                print(f"Found {len(pr_numbers)} related PRs: {', '.join(pr_numbers)}", file=sys.stderr)

                for pr in pr_numbers:
                    print(f"Fetching commits from PR #{pr}...", file=sys.stderr)
                    cmd = [
                        'gh', 'api',
                        f'repos/{organization}/{repository}/pulls/{pr}/commits',
                        '--jq', '.[].sha'
                    ]

                    print(f"Executing command: {' '.join(cmd)}", file=sys.stderr)
                    result = run_subprocess(cmd, capture_output=True, text=True, check=True)
                    pr_commits = result.stdout.strip().split('\n')
                    new_commits = [commit for commit in pr_commits if commit]

                    if new_commits:
                        print(f"Added {len(new_commits)} commits from PR #{pr}: {', '.join(new_commits)}", file=sys.stderr)
                        commit_ids.extend(new_commits)
                    else:
                        print(f"No commits found in PR #{pr}", file=sys.stderr)
            else:
                print("No related PRs found", file=sys.stderr)

        if not commit_ids:
            print("No linked commits found at all", file=sys.stderr)
            
        return commit_ids
    except Exception as e:
        print(f"Error fetching commit IDs: {e}", file=sys.stderr)
        if hasattr(e, 'stderr'):
            print(f"Command stderr: {e.stderr}", file=sys.stderr)
        return []

# Function to generate patches for a commit
def generate_patches_for_commit(organization, repository, commit_id, github_token, test_file_detector=is_test_file):
    try:
        # Use GitHub API to get the patch
        print(f"Using GitHub API to get patch for commit {commit_id} in {organization}/{repository} with token \"{github_token[:15]}...\"", file=sys.stderr)
        cmd = [
            'gh', 'api',
            f'repos/{organization}/{repository}/commits/{commit_id}',
            '-H', 'Accept: application/vnd.github.v3.patch',
            '-H', f'Authorization: Bearer {github_token}'
        ]
        result = run_subprocess(cmd, capture_output=True, text=True, check=False)

        # Check if the command was successful
        if result.returncode != 0:
            print(
                f"Error generating patches for commit {commit_id} using GitHub API: Command returned non-zero exit status {result.returncode}",
                file=sys.stderr)
            if result.stderr:
                print(f"Command stderr: {result.stderr}", file=sys.stderr)
            # Return empty patches but don't raise an exception
            return "", ""

        full_diff = result.stdout.strip()
        
        if not full_diff:
            print(f"No changes found in commit {commit_id}", file=sys.stderr)
            return "", ""
            
        # Split the diff into individual file diffs
        # Git diff format starts with "diff --git a/path b/path"
        file_diffs = re.split(r'(diff --git )', full_diff)
        
        # Process the split result to get proper file diffs
        processed_diffs = []
        for i in range(1, len(file_diffs), 2):
            if i+1 < len(file_diffs):
                processed_diffs.append(file_diffs[i] + file_diffs[i+1])
        
        # Separate source and test patches
        source_patches = []
        test_patches = []
        
        for diff in processed_diffs:
            # Extract file path from the diff
            file_path_match = re.search(r'diff --git a/(.*) b/', diff)
            if not file_path_match:
                continue
                
            file_path = file_path_match.group(1)
            
            # Determine if it's a test file
            if test_file_detector(file_path):
                test_patches.append(diff)
            else:
                source_patches.append(diff)
        
        # Combine patches
        source_patch = '\n'.join(source_patches)
        test_patch = '\n'.join(test_patches)
        
        return source_patch, test_patch
    except Exception as e:
        print(f"Error generating patches for commit {commit_id}: {e}", file=sys.stderr)
        if hasattr(e, 'stderr'):
            print(f"Command stderr: {e.stderr}", file=sys.stderr)
        return "", ""

# Function to extract issue labels via GitHub API
def fetch_issue_labels(organization, repository, issue_number):
    """
    Extracts labels from a GitHub issue and returns them as a list.

    Args:
        organization (str): GitHub organization name
        repository (str): GitHub repository name
        issue_number (str): Issue number

    Returns:
        list: List of label names from the issue
    """
    try:
        if issue_number == 'unknown' or not os.environ.get('GH_TOKEN', ''):
            print("Missing issue number or GitHub token, skipping label fetch", file=sys.stderr)
            return []

        print(f"Fetching labels for issue #{issue_number} in {organization}/{repository}...", file=sys.stderr)

        # Use GitHub CLI to fetch issue labels
        cmd = [
            'gh', 'api',
            f'repos/{organization}/{repository}/issues/{issue_number}',
            '--jq', '.labels[].name'
        ]

        print(f"Executing command: {' '.join(cmd)}", file=sys.stderr)
        result = run_subprocess(cmd, capture_output=True, text=True, check=True)
        labels = result.stdout.strip().split('\n')
        labels = [label for label in labels if label]  # Filter out empty strings

        if labels:
            print(f"Found {len(labels)} labels: {', '.join(labels)}", file=sys.stderr)
        else:
            print(f"No labels found for issue #{issue_number}", file=sys.stderr)

        return labels
    except Exception as e:
        print(f"Error fetching issue labels: {e}", file=sys.stderr)
        if hasattr(e, 'stderr'):
            print(f"Command stderr: {e.stderr}", file=sys.stderr)
        return []

# Function to read labels from common.json file
def read_labels(labels_path='.github/labels/common.json'):
    """
    Reads label definitions from common.json file and returns them as a list of names.

    Args:
        labels_path (str): Path to the labels JSON file, defaults to '.github/labels/common.json'

    Returns:
        list: List of label names from the common.json file
    """
    try:
        print(f"Reading labels from {labels_path}", file=sys.stderr)

        with open(labels_path, 'r') as f:
            labels_data = json.load(f)

        # Extract just the names from the label objects
        label_names = [label.get('name') for label in labels_data if label.get('name')]

        if label_names:
            print(f"Found {len(label_names)} labels in common.json: {', '.join(label_names)}", file=sys.stderr)
        else:
            print("No labels found in common.json", file=sys.stderr)

        return label_names
    except Exception as e:
        print(f"Error reading labels from common.json: {e}", file=sys.stderr)
        return []

# Function to merge patches for the same file from multiple commits
def merge_file_patches(file_patches):
    """
    Merges multiple patches for the same file into a single patch string by
    concatenating complete diff blocks. We intentionally avoid merging hunks
    from different commits into one file-level diff because hunks are based on
    different base versions and such merging often produces non-applicable
    patches. Instead, we preserve each "diff --git" block intact and return
    them in order, allowing patch tools to apply them sequentially.

    Args:
        file_patches (list): List of patch strings for the same file

    Returns:
        str: Concatenated patch blocks for the file
    """
    # Filter out empty entries
    patches = [p for p in (file_patches or []) if p and p.strip()]
    if not patches:
        return ""

    if len(patches) == 1:
        return patches[0]

    # Sanitize and deduplicate while preserving order
    sanitized = []
    seen = set()
    for p in patches:
        # Ensure we keep only from 'diff --git' header onward
        m = re.search(r'(diff --git[^\n]*\n.*)', p.strip(), re.DOTALL)
        block = m.group(1) if m else p.strip()
        if block and block not in seen:
            sanitized.append(block)
            seen.add(block)

    # Join as separate diff blocks. This produces a single patch text that
    # contains multiple complete diffs for the same file, which patch tools can
    # apply sequentially.
    return '\n\n'.join(sanitized)

# Function to generate patches for all commits related to a ticket
def generate_patches(organization, repository, commit_ids, github_token = os.environ.get("GH_TOKEN", ""), test_file_detector=is_test_file):
    """
    Generates source and test patches for all commits related to a ticket.
    Merges changes for the same files across multiple commits into single patches.
    
    Args:
        organization (str): GitHub organization name
        repository (str): GitHub repository name
        issue_number (str): Issue number
        commit_ids (list): List of commit IDs to process
        github_token (str): GitHub personal access token for authentication
        test_file_detector (function): Function to determine if a file is a test file
        
    Returns:
        tuple: (source_patch, test_patch) containing the combined patches for source and test files
    """
    if not commit_ids:
        print(f"No commits found for issue", file=sys.stderr)
        return "", ""
    
    print(f"Generating patches for {len(commit_ids)} commits...", file=sys.stderr)
    
    # Dictionaries to store patches by file path
    source_files = {}  # file_path -> list of patches
    test_files = {}    # file_path -> list of patches
    
    for commit_id in commit_ids:
        print(f"Generating patches for commit {commit_id}...", file=sys.stderr)
        source_patch, test_patch = generate_patches_for_commit(organization, repository, commit_id, github_token, test_file_detector)
        
        # Process source patches
        if source_patch:
            # Split the patch into individual file diffs
            file_diffs = re.split(r'(diff --git )', source_patch)
            
            # Process the split result to get proper file diffs
            for i in range(1, len(file_diffs), 2):
                if i+1 < len(file_diffs):
                    diff = file_diffs[i] + file_diffs[i+1]
                    
                    # Extract file path from the diff
                    file_path_match = re.search(r'diff --git a/(.*) b/', diff)
                    if file_path_match:
                        file_path = file_path_match.group(1)
                        
                        if file_path not in source_files:
                            source_files[file_path] = []
                        source_files[file_path].append(diff)
            
            print(f"Added source patch for commit {commit_id}", file=sys.stderr)
        
        # Process test patches
        if test_patch:
            # Split the patch into individual file diffs
            file_diffs = re.split(r'(diff --git )', test_patch)
            
            # Process the split result to get proper file diffs
            for i in range(1, len(file_diffs), 2):
                if i+1 < len(file_diffs):
                    diff = file_diffs[i] + file_diffs[i+1]
                    
                    # Extract file path from the diff
                    file_path_match = re.search(r'diff --git a/(.*) b/', diff)
                    if file_path_match:
                        file_path = file_path_match.group(1)
                        
                        if file_path not in test_files:
                            test_files[file_path] = []
                        test_files[file_path].append(diff)
            
            print(f"Added test patch for commit {commit_id}", file=sys.stderr)
    
    # Merge patches for each file and combine into final patches
    merged_source_patches = []
    for file_path, patches in source_files.items():
        merged_patch = merge_file_patches(patches)
        if merged_patch:
            merged_source_patches.append(merged_patch)
            print(f"Merged {len(patches)} patches for source file: {file_path}", file=sys.stderr)
    
    merged_test_patches = []
    for file_path, patches in test_files.items():
        merged_patch = merge_file_patches(patches)
        if merged_patch:
            merged_test_patches.append(merged_patch)
            print(f"Merged {len(patches)} patches for test file: {file_path}", file=sys.stderr)
    
    # Combine all merged patches
    combined_source_patch = '\n\n'.join(merged_source_patches)
    combined_test_patch = '\n\n'.join(merged_test_patches)
    
    return combined_source_patch, combined_test_patch