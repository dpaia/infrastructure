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
def detect_build_system():
    """
    Detects the build system used in the project and returns a dictionary with the following keys:
    - is_maven: "true" if Maven build system is detected (pom.xml exists), "false" otherwise
    - gradle: "groovy" if Gradle with Groovy DSL is detected, "kotlin" if Gradle with Kotlin DSL is detected, not present if Gradle is not detected

    Returns:
        dict: A dictionary containing build system information
    """
    result = ""

    # Check for Maven (pom.xml)
    maven_files = glob.glob("**/pom.xml", recursive=True)
    if maven_files:
        return "maven"

    # Check for Gradle (build.gradle or build.gradle.kts)
    gradle_groovy_files = glob.glob("**/build.gradle", recursive=True)
    gradle_kotlin_files = glob.glob("**/build.gradle.kts", recursive=True)

    # If Gradle is detected, determine the type
    if gradle_groovy_files or gradle_kotlin_files:
        # If both types exist, prioritize the one with more files
        # If equal, prioritize Kotlin as it's newer
        if len(gradle_kotlin_files) >= len(gradle_groovy_files):
            return "gradle-kotlin"
        else:
            return "gradle"

    return result

# Wrap the main part of the script in a try-except block to ensure we always output valid JSON
try:
    # Process test fields
    fail_to_pass_json, pass_to_pass_json = process_test_fields(organization, repository, issue_number)

    # Detect build system
    build_system = detect_build_system()
    
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
        "is_maven": build_system == "maven",
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