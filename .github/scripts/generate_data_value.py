#!/usr/bin/env python3

import os
import json
import datetime
import re

# Get required input parameters from environment variables
issue_number = os.environ.get('ISSUE_NUMBER', 'unknown')
repository = os.environ.get('REPOSITORY', 'unknown')
latest_commit = os.environ.get('LATEST_COMMIT', '')
base_commit = os.environ.get('BASE_COMMIT', '')

# Generate current timestamp in ISO format
current_time = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S%z')
if not current_time.endswith('+0000'):
    current_time += '+00:00'

# Format repository
repo_with_git = f"{repository}.git"
if not repo_with_git.startswith('jetbrains-eval-lab/'):
    repo_with_git = f"jetbrains-eval-lab/{repo_with_git}"

# Create instance_id: <repository name>-<last commit short hash>
short_hash = latest_commit[:8] if latest_commit else 'unknown'
instance_id = f"jetbrains__eval__lab__{repository.replace('-', '__')}-{short_hash}"

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
    "problem_statement": "Add validation annotations to the Pet, Visit, and Owner entities to ensure required fields are not null. Implement a global exception handler to manage validation errors across the REST API. Modify relevant methods in the controllers to return appropriate responses for validation issues.",
    "version": "0.1",
    "is_maven": "true"
}

# Output the value as JSON string
print(json.dumps(data))
