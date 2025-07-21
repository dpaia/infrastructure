#!/usr/bin/env python3
import json
import os
import sys

# Import functions from generate_data.py
from generate_data import process_test_fields

def main():
    # Get environment variables
    organization = os.environ.get('ORGANIZATION', 'unknown')
    repository = os.environ.get('REPOSITORY', 'unknown')
    issue_number = os.environ.get('ISSUE_NUMBER', 'unknown')
    
    # Process test fields
    fail_to_pass_json, pass_to_pass_json = process_test_fields(organization, repository, issue_number)
    
    # Create output JSON
    output = {
        "FAIL_TO_PASS": fail_to_pass_json,
        "PASS_TO_PASS": pass_to_pass_json
    }
    
    # Print JSON to stdout
    print(json.dumps(output))

if __name__ == "__main__":
    main()