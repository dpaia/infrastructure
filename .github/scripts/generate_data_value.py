#!/usr/bin/env python3

import os
import json
import datetime
import subprocess
import sys
import re

# Get required input parameters from environment variables
issue_number = os.environ.get('ISSUE_NUMBER', 'unknown')
repository = os.environ.get('REPOSITORY', 'unknown')
organization = os.environ.get('ORGANIZATION', 'jetbrains-eval-lab')
latest_commit = os.environ.get('LATEST_COMMIT', '')
base_commit = os.environ.get('BASE_COMMIT', '')
gh_token = os.environ.get('GH_TOKEN', '')

# Create full repository name
full_repository = f"{organization}/{repository}"
org_name = organization
repo_name = repository

# Generate current timestamp in ISO format
current_time = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S%z')
if not current_time.endswith('+0000'):
    current_time += '+00:00'

# Format repository
repo_with_git = f"{full_repository}.git"

# Create instance_id using organization and repository name
short_hash = latest_commit[:8] if latest_commit else 'unknown'
org_for_id = org_name.replace('-', '__')
repo_for_id = repo_name.replace('-', '__')
instance_id = f"{org_for_id}__{repo_for_id}-{short_hash}"

# Function to convert comma-separated list to JSON array string
def to_json_array(value_str):
    if not value_str:
        return "[]"

    # Split by comma and strip whitespace
    items = [item.strip() for item in value_str.split(',')]
    # Filter out empty items
    items = [item for item in items if item]

    if not items:
        return "[]"

    # Convert to JSON array string
    return json.dumps(items)

# Function to extract FAIL_TO_PASS and PASS_TO_PASS from text
def extract_test_fields(text):
    fail_to_pass = "[]"
    pass_to_pass = "[]"

    if text:
        # Find FAIL_TO_PASS pattern
        fail_matches = re.search(r'FAIL_TO_PASS:\s*(.+?)(?:\n|$)', text)
        if fail_matches:
            fail_to_pass = fail_matches.group(1).strip()

        # Find PASS_TO_PASS pattern
        pass_matches = re.search(r'PASS_TO_PASS:\s*(.+?)(?:\n|$)', text)
        if pass_matches:
            pass_to_pass_value = pass_matches.group(1).strip()
            pass_to_pass = to_json_array(pass_to_pass_value) if pass_to_pass_value else "[]"

    return fail_to_pass, pass_to_pass

# Function to fetch issue comments
def fetch_issue_comments():
    try:
        if issue_number == 'unknown' or not gh_token:
            return []

        cmd = [
            'gh', 'api', 
            f'repos/{full_repository}/issues/{issue_number}/comments',
            '--jq', '.[].body'
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        comments = result.stdout.strip().split('\n')
        return [comment for comment in comments if comment]
    except Exception as e:
        print(f"Error fetching issue comments: {e}", file=sys.stderr)
        return []

# Function to fetch commit messages for linked commits
def fetch_linked_commit_messages():
    try:
        if issue_number == 'unknown' or not gh_token:
            return []

        # First, get linked commit IDs
        cmd = [
            'gh', 'api', 
            f'repos/{full_repository}/issues/{issue_number}/timeline',
            '--jq', '.[] | select(.event == "referenced" and .commit_id != null) | .commit_id'
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        commit_ids = result.stdout.strip().split('\n')
        commit_ids = [commit_id for commit_id in commit_ids if commit_id]

        if not commit_ids:
            # Try to get commits from PRs
            cmd = [
                'gh', 'api',
                f'repos/{full_repository}/issues/{issue_number}/timeline',
                '--jq', '.[] | select(.event == "cross-referenced" and .source.issue.pull_request != null) | .source.issue.number'
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            pr_numbers = result.stdout.strip().split('\n')
            pr_numbers = [pr for pr in pr_numbers if pr]

            for pr in pr_numbers:
                cmd = [
                    'gh', 'api',
                    f'repos/{full_repository}/pulls/{pr}/commits',
                    '--jq', '.[].sha'
                ]

                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                pr_commits = result.stdout.strip().split('\n')
                commit_ids.extend([commit for commit in pr_commits if commit])

        # Now fetch commit messages for each commit
        messages = []
        for commit_id in commit_ids:
            cmd = [
                'gh', 'api',
                f'repos/{full_repository}/commits/{commit_id}',
                '--jq', '.commit.message'
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            message = result.stdout.strip()
            if message:
                messages.append(message)

        return messages
    except Exception as e:
        print(f"Error fetching commit messages: {e}", file=sys.stderr)
        return []

# Default problem statement is empty
default_problem_statement = ""

# Fetch issue description from GitHub API
problem_statement = default_problem_statement
try:
    if issue_number != 'unknown' and gh_token:
        # Use GitHub CLI to fetch issue description
        cmd = [
            'gh', 'api', 
            f'repos/{full_repository}/issues/{issue_number}',
            '--jq', '.body'
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        issue_description = result.stdout.strip()

        if issue_description:
            problem_statement = issue_description
            print(f"Successfully fetched issue description for issue #{issue_number}", file=sys.stderr)
        else:
            print(f"Issue #{issue_number} has no description, using empty problem statement", file=sys.stderr)
    else:
        print("Missing issue number or GitHub token, using empty problem statement", file=sys.stderr)
except Exception as e:
    print(f"Error fetching issue description: {e}", file=sys.stderr)
    print("Using empty problem statement", file=sys.stderr)

# Fetch and parse test fields
fail_to_pass_value = "[]"
pass_to_pass_value = "[]"

# First check issue comments
print("Checking issue comments for test fields...", file=sys.stderr)
comments = fetch_issue_comments()
for comment in reversed(comments):  # Start with the most recent comments
    comment_fail, comment_pass = extract_test_fields(comment)
    if comment_fail:
        fail_to_pass_value = comment_fail
        print(f"Found FAIL_TO_PASS in issue comment: {fail_to_pass_value}", file=sys.stderr)

    if comment_pass != "[]":
        pass_to_pass_value = comment_pass
        print(f"Found PASS_TO_PASS in issue comment: {pass_to_pass_value}", file=sys.stderr)

    if fail_to_pass_value and pass_to_pass_value != "[]":
        break

# If not found in comments, check commit messages
if not fail_to_pass_value or pass_to_pass_value == "[]":
    print("Checking commit messages for test fields...", file=sys.stderr)
    commit_messages = fetch_linked_commit_messages()
    for message in reversed(commit_messages):  # Start with the most recent commits
        commit_fail, commit_pass = extract_test_fields(message)

        if not fail_to_pass_value and commit_fail:
            fail_to_pass_value = commit_fail
            print(f"Found FAIL_TO_PASS in commit message: {fail_to_pass_value}", file=sys.stderr)

        if pass_to_pass_value == "[]" and commit_pass != "[]":
            pass_to_pass_value = commit_pass
            print(f"Found PASS_TO_PASS in commit message: {pass_to_pass_value}", file=sys.stderr)

        if fail_to_pass_value and pass_to_pass_value != "[]":
            break

# Convert FAIL_TO_PASS to JSON array if it has a value
if fail_to_pass_value:
    fail_to_pass_json = to_json_array(fail_to_pass_value)
else:
    fail_to_pass_json = ""

# Create the JSON structure
data = {
    "instance_id": instance_id,
    "issue_numbers": f"[\"{issue_number}\"]",
    "repo": repo_with_git,
    "patch": "",
    "FAIL_TO_PASS": fail_to_pass_json,
    "PASS_TO_PASS": pass_to_pass_value,
    "created_at": current_time,
    "base_commit": base_commit,
    "problem_statement": problem_statement,
    "version": "0.1",
    "is_maven": "true"
}

# Output the value as JSON string
print(json.dumps(data))
