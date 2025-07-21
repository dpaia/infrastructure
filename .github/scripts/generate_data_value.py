#!/usr/bin/env python3

import os
import json
import datetime
import subprocess
import sys

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

# Create the JSON structure
data = {
    "instance_id": instance_id,
    "issue_numbers": f"[\"{issue_number}\"]",
    "repo": repo_with_git,
    "patch": "",
    "FAIL_TO_PASS": "",
    "PASS_TO_PASS": "[]",
    "created_at": current_time,
    "base_commit": base_commit,
    "problem_statement": problem_statement,
    "version": "0.1",
    "is_maven": "true"
}

# Output the value as JSON string
print(json.dumps(data))
