#!/usr/bin/env python3
import os
import sys

from generate_data import process_test_fields

# Get required input parameters from environment variables
issue_number = os.environ.get('ISSUE_NUMBER', 'unknown')
repository = os.environ.get('REPOSITORY', 'unknown')
organization = os.environ.get('ORGANIZATION', 'jetbrains-eval-lab')

try:
    # Process test fields
    fail_to_pass_json, pass_to_pass_json = process_test_fields(organization, repository, issue_number)

    # Output the results
    print(f"fail_to_pass={fail_to_pass_json}")
    print(f"pass_to_pass={pass_to_pass_json}")
    print("has_error=false")
except Exception as e:
    print(f"Error extracting test fields: {e}", file=sys.stderr)
    print("fail_to_pass=[]")
    print("pass_to_pass=[]")
    print("has_error=true")