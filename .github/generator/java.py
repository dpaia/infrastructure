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


# Function to detect the build system in a project
def detect_build_system(organization, repository):
    # Use GitHub API to find build files
    try:
        # Find all pom.xml files
        maven_files = _find_files_with_github_api(organization, repository, "pom.xml")
        if maven_files:
            return "maven"
        
        # Find all build.gradle files
        gradle_groovy_files = _find_files_with_github_api(organization, repository, "build.gradle")
        
        # Find all build.gradle.kts files
        gradle_kotlin_files = _find_files_with_github_api(organization, repository, "build.gradle.kts")
        
        # If Gradle is detected, determine the type
        if gradle_groovy_files or gradle_kotlin_files:
            # If both types exist, prioritize the one with more files
            # If equal, prioritize Kotlin as it's newer
            if len(gradle_kotlin_files) >= len(gradle_groovy_files):
                return "gradle-kotlin"
            else:
                return "gradle"
        
        return ""
    except Exception as e:
        print(f"Error using GitHub API to detect build system: {e}", file=sys.stderr)
        # Fall back to local detection
        return ""

def _find_files_with_github_api(organization, repository, filename):
    cmd = [
        'gh', 'api',
        f'search/code?q=filename:{filename}+repo:{organization}/{repository}',
        '--jq', '.items[].path'
    ]
    
    try:
        result = run_subprocess(cmd, capture_output=True, text=True, check=True)
        files = result.stdout.strip().split('\n')
        return [file for file in files if file]
    except Exception as e:
        print(f"Error searching for {filename}: {e}", file=sys.stderr)
        return []

# Wrap the main part of the script in a try-except block to ensure we always output valid JSON
try:
    # Process test fields
    fail_to_pass_json, pass_to_pass_json = process_test_fields(organization, repository, issue_number)

    # Generate source and test patches
    source_patch, test_patch = generate_patches(organization, repository, issue_number, is_test_file)
    
    # Detect build system
    build_system = detect_build_system(organization, repository)
    
    # Create the JSON structure
    data = {
        "instance_id": generate_instance_id(organization, repository, issue_number),
        "issue_numbers": f"[\"{issue_number}\"]",
        "repo": f"{organization}/{repository}.git",
        "patch": f"{source_patch}",
        "test_patch": f"{test_patch}",
        "FAIL_TO_PASS": fail_to_pass_json,
        "PASS_TO_PASS": pass_to_pass_json,
        "created_at": current_time,
        "base_commit": os.environ.get('BASE_COMMIT', ''),
        "problem_statement": fetch_problem_statement(organization, repository, issue_number),
        "version": "0.1",
        "is_maven": f"{build_system == "maven"}",
        "build_system": build_system
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

    # Try to detect build system even in error case
    try:
        build_system = detect_build_system()
    except:
        # Fallback to default if build system detection fails
        build_system = ""
        
    error_data = {
        "instance_id": instance_id,
        "issue_numbers": f"[\"{issue_number}\"]",
        "repo": f"{organization}/{repository}.git",
        "patch": "",
        "test_patch": "",
        "FAIL_TO_PASS": "[]",
        "PASS_TO_PASS": "[]",
        "created_at": current_time,
        "base_commit": os.environ.get('BASE_COMMIT', ''),
        "problem_statement": "",
        "version": "0.1",
        "is_maven": build_system == "maven",
        "build_system": build_system,
        "error": str(e),
        "has_error": True  # Flag to indicate error
    }

    # Output the error data as JSON
    print(json.dumps(error_data))