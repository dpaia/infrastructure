#!/usr/bin/env python3

import datetime

from utils.generate_data import *


# Get required input parameters from environment variables
issue_number = os.environ.get('ISSUE_NUMBER', 'unknown')
repository = os.environ.get('REPOSITORY', 'unknown')
organization = os.environ.get('ORGANIZATION', 'jetbrains-eval-lab')
latest_commit = os.environ.get('LATEST_COMMIT', '')

# Generate current timestamp in ISO format
current_time = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S%z')
if not current_time.endswith('+0000'):
    current_time += '+00:00'

# Wrap the main part of the script in a try-except block to ensure we always output valid JSON
try:
    # Process test fields
    fail_to_pass_json, pass_to_pass_json = process_test_fields(organization, repository, issue_number)

    # Create the JSON structure
    data = {
        "instance_id": generate_instance_id(organization, repository, issue_number),
        "issue_numbers": f"[\"{issue_number}\"]",
        "repo": f"{organization}/{repository}.git",
        "patch": "",
        "FAIL_TO_PASS": fail_to_pass_json,
        "PASS_TO_PASS": pass_to_pass_json,
        "created_at": current_time,
        "base_commit": os.environ.get('BASE_COMMIT', ''),
        "problem_statement": fetch_problem_statement(organization, repository, issue_number),
        "version": "0.1",
        "is_maven": "true"
    }

    # Output the value as JSON string
    print(json.dumps(data))
except Exception as e:
    # If any error occurs, still output valid JSON with error information
    print(f"Error in script execution: {e}", file=sys.stderr)
    if hasattr(e, 'traceback'):
        print(f"Traceback: {e.traceback}", file=sys.stderr)

    # Generate instance_id even in case of error
    instance_id = generate_instance_id(organization, repository, latest_commit)

    error_data = {
        "instance_id": instance_id,
        "issue_numbers": f"[\"{issue_number}\"]",
        "repo": f"{organization}/{repository}.git",
        "patch": "",
        "FAIL_TO_PASS": "[]",
        "PASS_TO_PASS": "[]",
        "created_at": current_time,
        "base_commit": os.environ.get('BASE_COMMIT', ''),
        "problem_statement": "",
        "version": "0.1",
        "is_maven": "true",
        "error": str(e),
        "has_error": True  # Flag to indicate error
    }

    # Output the error data as JSON
    print(json.dumps(error_data))