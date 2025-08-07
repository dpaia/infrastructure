#!/usr/bin/env python3

import datetime

from utils.generate_data import *


# Get required input parameters from environment variables
issue_number = os.environ.get('ISSUE_NUMBER', 'unknown')
repository = os.environ.get('REPOSITORY', 'unknown')
organization = os.environ.get('ORGANIZATION', 'jetbrains-eval-lab')
latest_commit = os.environ.get('LATEST_COMMIT', '')
linked_commits = json.loads(os.environ.get('LINKED_COMMITS', '')) if os.environ.get('LINKED_COMMITS', '') else []
fail_to_pass = os.environ.get('FAIL_TO_PASS', '')
pass_to_pass = os.environ.get('PASS_TO_PASS', '')
version_str = os.environ.get('VERSION', '')
test_args = os.environ.get('TEST_ARGS', '')
version = float(version_str) + 1 if version_str.strip() else 1.0

# Generate current timestamp in ISO format
current_time = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S%z')
if not current_time.endswith('+0000'):
    current_time += '+00:00'


# Function to detect the build system in a project
def detect_build_system(organization, repository, commit=None):
    """
    Detects the build system used in a project by searching for build files.
    
    Args:
        organization (str): The GitHub organization name
        repository (str): The GitHub repository name
        commit (str, optional): The commit hash to check. If None, checks the current state.
    
    Returns:
        str: A string indicating the detected build system:
            - "maven" if Maven is detected (pom.xml exists)
            - "gradle-kotlin" if Gradle with Kotlin DSL is detected (build.gradle.kts exists)
            - "gradle" if Gradle with Groovy DSL is detected (build.gradle exists)
            - "" (empty string) if no build system is detected
    """
    print(f"Starting build system detection for {organization}/{repository} at commit: {commit if commit else 'current'}", file=sys.stderr)
    # Use GitHub API to find build files
    try:
        # Find all pom.xml files
        maven_files = _find_files_with_github_api(organization, repository, "pom.xml", commit)
        print(f"Maven files found: {len(maven_files)}", file=sys.stderr)
        if maven_files:
            print(f"Maven files: {maven_files}", file=sys.stderr)
            print(f"Build system detected: maven", file=sys.stderr)
            return "maven"
        
        # Find all build.gradle files
        gradle_groovy_files = _find_files_with_github_api(organization, repository, "build.gradle", commit)
        print(f"Gradle Groovy files found: {len(gradle_groovy_files)}", file=sys.stderr)
        if gradle_groovy_files:
            print(f"Gradle Groovy files: {gradle_groovy_files}", file=sys.stderr)
        
        # Find all build.gradle.kts files
        gradle_kotlin_files = _find_files_with_github_api(organization, repository, "build.gradle.kts", commit)
        print(f"Gradle Kotlin files found: {len(gradle_kotlin_files)}", file=sys.stderr)
        if gradle_kotlin_files:
            print(f"Gradle Kotlin files: {gradle_kotlin_files}", file=sys.stderr)
        
        # If Gradle is detected, determine the type
        if gradle_groovy_files or gradle_kotlin_files:
            print(f"Gradle detected. Determining type between Groovy ({len(gradle_groovy_files)} files) and Kotlin ({len(gradle_kotlin_files)} files)", file=sys.stderr)
            # If both types exist, prioritize the one with more files
            # If equal, prioritize Kotlin as it's newer
            if len(gradle_kotlin_files) >= len(gradle_groovy_files):
                print(f"Selected Gradle Kotlin as build system (more or equal files than Groovy)", file=sys.stderr)
                print(f"Build system detected: gradle-kotlin", file=sys.stderr)
                return "gradle-kotlin"
            else:
                print(f"Selected Gradle Groovy as build system (more files than Kotlin)", file=sys.stderr)
                print(f"Build system detected: gradle", file=sys.stderr)
                return "gradle"

        print(f"No build system detected for {organization}/{repository}", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"Error using GitHub API to detect build system: {e}", file=sys.stderr)
        print(f"No build system detected for {organization}/{repository} after API error", file=sys.stderr)
        return ""

def _find_files_with_github_api(organization, repository, filename, commit=None):
    """
    Uses GitHub API to find files with a specific name in the repository at a specific commit.
    
    Args:
        organization (str): The GitHub organization name
        repository (str): The GitHub repository name
        filename (str): The filename to search for
        commit (str, optional): The commit hash to check. If None, checks the current state.
        
    Returns:
        list: A list of paths to the found files
    """
    print(f"Searching for {filename} in {organization}/{repository} at commit: {commit if commit else 'current'}", file=sys.stderr)
    
    # Determine the tree reference (branch or commit)
    tree_ref = commit if commit else 'HEAD'
    
    # Use the GitHub tree API to get all files in the repository
    api_endpoint = f'repos/{organization}/{repository}/git/trees/{tree_ref}'
    
    print(f"GitHub API endpoint: {api_endpoint}", file=sys.stderr)
    
    cmd = [
        'gh', 'api',
        api_endpoint,
        '--jq', '.tree[] | select(.path) | .path'
    ]
    
    print(f"Running command: {' '.join(cmd)}", file=sys.stderr)
    
    try:
        result = run_subprocess(cmd, capture_output=True, text=True, check=True)
        all_files = result.stdout.strip().split('\n')
        all_files = [file for file in all_files if file]
        
        # Filter files to only include those with the specified filename
        files = [file for file in all_files if os.path.basename(file) == filename]
        
        print(f"GitHub API found {len(files)} {filename} files", file=sys.stderr)
        return files
    except Exception as e:
        print(f"Error searching for {filename}: {e}", file=sys.stderr)
        return []

# Wrap the main part of the script in a try-except block to ensure we always output valid JSON
try:
    # Generate source and test patches
    source_patch, test_patch = generate_patches(organization, repository, issue_number, linked_commits, is_test_file)

    if source_patch == "":
        source_patch = test_patch
        test_patch = ""
    
    # Get base commit from environment variables
    base_commit = os.environ.get('BASE_COMMIT', '')

    # Detect build system at base_commit if available, otherwise use current state
    build_system = detect_build_system(organization, repository, base_commit if base_commit else None)

    # Fetch issue labels and common labels
    issue_labels = fetch_issue_labels(organization, repository, issue_number)
    common_labels = read_labels('.github/labels/common.json')

    # Filter out common labels to create tags
    tags = [label for label in issue_labels if label not in common_labels]

    # Create the JSON structure
    data = {
        "instance_id": generate_instance_id(organization, repository, issue_number),
        "issue_numbers": f"[\"{issue_number}\"]",
        "tags": json.dumps(tags),
        "repo": f"{organization}/{repository}.git",
        "patch": f"{source_patch}",
        "test_patch": f"{test_patch}",
        "FAIL_TO_PASS": fail_to_pass,
        "PASS_TO_PASS": pass_to_pass,
        "created_at": current_time,
        "base_commit": os.environ.get('BASE_COMMIT', ''),
        "problem_statement": fetch_problem_statement(organization, repository, issue_number).get('body', ''),
        "version": f"{version if version else 1}",
        "is_maven": f"{build_system == "maven"}",
        "build_system": build_system,
        "test_args": test_args
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
        # Get base commit from environment variables
        base_commit = os.environ.get('BASE_COMMIT', '')
        
        # Detect build system at base_commit if available, otherwise use current state
        build_system = detect_build_system(organization, repository, base_commit if base_commit else None)
    except Exception as e:
        # Fallback to default if build system detection fails
        print(f"Error detecting build system in error handler: {e}", file=sys.stderr)
        build_system = ""
        
    error_data = {
        "instance_id": instance_id,
        "issue_numbers": f"[\"{issue_number}\"]",
        "tags": "[]",
        "repo": f"{organization}/{repository}.git",
        "patch": "",
        "test_patch": "",
        "FAIL_TO_PASS": "[]",
        "PASS_TO_PASS": "[]",
        "created_at": current_time,
        "base_commit": os.environ.get('BASE_COMMIT', ''),
        "problem_statement": "",  # Already an empty string, no need to change
        "version": f"{version if version else 1}",
        "is_maven": build_system == "maven",
        "build_system": build_system,
        "test_args": test_args,
        "error": str(e),
        "has_error": True  # Flag to indicate error
    }

    # Output the error data as JSON
    print(json.dumps(error_data))