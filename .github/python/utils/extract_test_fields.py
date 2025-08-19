#!/usr/bin/env python3
import importlib
import json
import os
import re
import sys

# Get required input parameters from environment variables
issue_number = os.environ.get('ISSUE_NUMBER', 'unknown')
repository = os.environ.get('REPOSITORY', 'unknown')
organization = os.environ.get('ORGANIZATION', 'jetbrains-eval-lab')


# Create a wrapper function for subprocess.run that won't be affected by mocks
def run_subprocess(cmd, **kwargs):
    # Get the real subprocess module, even if it's been mocked
    real_subprocess = importlib.import_module('subprocess')
    return real_subprocess.run(cmd, **kwargs)


# Function to convert comma-separated list to JSON array string
def to_json_array(value_str):
    if not value_str or value_str == "[]":
        return "[]"

    # Check if it's already a JSON array
    if value_str.startswith("[") and value_str.endswith("]"):
        try:
            # Validate it's proper JSON
            json.loads(value_str)
            return value_str  # Return as-is if it's valid JSON
        except json.JSONDecodeError:
            # Not valid JSON, proceed with parsing
            pass

    # Split by comma and strip whitespace
    items = [item.strip() for item in value_str.split(',')]
    # Filter out empty items
    items = [item for item in items if item]

    if not items:
        return "[]"

    # Convert to JSON array string
    return json.dumps(items)

# Function to extract FAIL_TO_PASS, PASS_TO_PASS, and METADATA from text
def extract_test_fields(text):
    fail_to_pass = ""
    pass_to_pass = ""
    metadata = ""

    if text:
        # Find FAIL_TO_PASS pattern
        fail_matches = re.search(r'FAIL_TO_PASS:\s*(.+?)(?:\n|$)', text)
        if fail_matches:
            fail_to_pass = fail_matches.group(1).strip()

        # Find PASS_TO_PASS pattern
        pass_matches = re.search(r'PASS_TO_PASS:\s*(.+?)(?:\n|$)', text)
        if pass_matches:
            pass_to_pass = pass_matches.group(1).strip()

        # Find METADATA pattern in the same comment
        if fail_to_pass or pass_to_pass:
            metadata_matches = re.search(r'METADATA:\s*(.+?)(?:\n|$)', text)
            if metadata_matches:
                metadata = metadata_matches.group(1).strip()

    return fail_to_pass, pass_to_pass, metadata


# Function to fetch commit messages for linked commits
def fetch_linked_commit_messages(organization_repository, issue_number):
    try:
        # Check for test environment variable that provides mocked commit messages
        test_commit_message = os.environ.get('TEST_COMMIT_MESSAGE', '')
        if test_commit_message:
            print(f"Using test commit message from environment variable", file=sys.stderr)
            return [test_commit_message]

        if issue_number == 'unknown' or not os.environ.get('GH_TOKEN', ''):
            print("Missing issue number or GitHub token, skipping commit message fetch", file=sys.stderr)
            return []

        print(f"Fetching linked commits for issue #{issue_number} in {organization_repository}...", file=sys.stderr)

        # First, get linked commit IDs
        cmd = [
            'gh', 'api',
            f'repos/{organization_repository}/issues/{issue_number}/timeline',
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
                f'repos/{organization_repository}/issues/{issue_number}/timeline',
                '--jq',
                '.[] | select(.event == "cross-referenced" and .source.issue.pull_request != null) | .source.issue.number'
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
                        f'repos/{organization_repository}/pulls/{pr}/commits',
                        '--jq', '.[].sha'
                    ]

                    print(f"Executing command: {' '.join(cmd)}", file=sys.stderr)
                    result = run_subprocess(cmd, capture_output=True, text=True, check=True)
                    pr_commits = result.stdout.strip().split('\n')
                    new_commits = [commit for commit in pr_commits if commit]

                    if new_commits:
                        print(f"Added {len(new_commits)} commits from PR #{pr}: {', '.join(new_commits)}",
                              file=sys.stderr)
                        commit_ids.extend(new_commits)
                    else:
                        print(f"No commits found in PR #{pr}", file=sys.stderr)
            else:
                print("No related PRs found", file=sys.stderr)

        if not commit_ids:
            print("No linked commits found at all", file=sys.stderr)
            return []

        # Now fetch commit messages for each commit
        print(f"Fetching messages for {len(commit_ids)} commits...", file=sys.stderr)
        messages = []
        for i, commit_id in enumerate(commit_ids):
            print(f"Fetching message for commit {i + 1}/{len(commit_ids)}: {commit_id}", file=sys.stderr)
            cmd = [
                'gh', 'api',
                f'repos/{organization_repository}/commits/{commit_id}',
                '--jq', '.commit.message'
            ]

            result = run_subprocess(cmd, capture_output=True, text=True, check=True)
            message = result.stdout.strip()
            if message:
                # Print just the first line of the commit message (usually the subject)
                first_line = message.split('\n')[0]
                print(f"Commit {commit_id} message: {first_line[:50]}{'...' if len(first_line) > 50 else ''}",
                      file=sys.stderr)

                # Check if the message contains test fields and log them
                if "FAIL_TO_PASS:" in message or "PASS_TO_PASS:" in message:
                    print(f"Found test fields in commit {commit_id}", file=sys.stderr)
                    print(f"Full commit message:", file=sys.stderr)
                    print(f"---BEGIN COMMIT MESSAGE---", file=sys.stderr)
                    print(message, file=sys.stderr)
                    print(f"---END COMMIT MESSAGE---", file=sys.stderr)

                messages.append(message)
            else:
                print(f"No message found for commit {commit_id}", file=sys.stderr)

        print(f"Retrieved {len(messages)} commit messages in total", file=sys.stderr)
        return messages
    except Exception as e:
        print(f"Error fetching commit messages: {e}", file=sys.stderr)
        if hasattr(e, 'stderr'):
            print(f"Command stderr: {e.stderr}", file=sys.stderr)
        return []

# Function to process test fields from various sources
def process_test_fields(organization_repository, issue_number):
    fail_to_pass_value = ""
    pass_to_pass_value = ""
    metadata_value = ""
    comment_id = ""

    # Check for direct test environment variables first
    test_fail_to_pass = os.environ.get('TEST_FAIL_TO_PASS', '')
    test_pass_to_pass = os.environ.get('TEST_PASS_TO_PASS', '')
    metadata = os.environ.get('METADATA', '')

    if test_fail_to_pass:
        fail_to_pass_value = test_fail_to_pass
        print(f"Using FAIL_TO_PASS from TEST_FAIL_TO_PASS environment variable: {fail_to_pass_value}", file=sys.stderr)

    if test_pass_to_pass:
        pass_to_pass_value = test_pass_to_pass
        print(f"Using PASS_TO_PASS from TEST_PASS_TO_PASS environment variable: {pass_to_pass_value}", file=sys.stderr)

    if metadata:
        metadata_value = metadata
        print(f"Using METADATA from METADATA environment variable: {metadata_value}", file=sys.stderr)

    # If not found in environment variables, check issue comments
    if not test_fail_to_pass and not test_pass_to_pass:
        # First check issue comments
        print("Checking issue comments for test fields...", file=sys.stderr)
        comments = fetch_issue_comments(organization_repository, issue_number)
        for comment in reversed(comments):  # Start with the most recent comments
            comment_body = comment["body"]
            comment_fail, comment_pass, comment_metadata = extract_test_fields(comment_body)
            if comment_fail:
                fail_to_pass_value = comment_fail
                comment_id = str(comment["id"])
                print(f"Found FAIL_TO_PASS in issue comment {comment_id}: {fail_to_pass_value}", file=sys.stderr)

            if comment_pass != "":
                pass_to_pass_value = comment_pass
                comment_id = str(comment["id"])
                print(f"Found PASS_TO_PASS in issue comment {comment_id}: {pass_to_pass_value}", file=sys.stderr)

            if comment_metadata and (comment_fail or comment_pass):
                metadata_value = comment_metadata
                print(f"Found METADATA in issue comment {comment_id}: {metadata_value}", file=sys.stderr)

            if fail_to_pass_value or pass_to_pass_value:
                break

        # If not found in comments, check commit messages
        if not fail_to_pass_value and not pass_to_pass_value:
            print("Checking commit messages for test fields...", file=sys.stderr)
            commit_messages = fetch_linked_commit_messages(organization_repository, issue_number)

            # Log how many messages we're processing
            print(f"Processing {len(commit_messages)} commit messages for test fields", file=sys.stderr)

            for index, message in enumerate(reversed(commit_messages)):  # Start with the most recent commits
                print(f"Processing commit message {index + 1}/{len(commit_messages)}", file=sys.stderr)

                # Debug: Check if we're getting multiline messages
                lines = message.split('\n')
                print(f"Commit message has {len(lines)} lines", file=sys.stderr)

                # Print each line for debugging
                print("Message lines:", file=sys.stderr)
                for i, line in enumerate(lines):
                    print(f"  Line {i + 1}: {line}", file=sys.stderr)

                # Explicitly check for the patterns
                if "FAIL_TO_PASS:" in message:
                    print(f"Found FAIL_TO_PASS pattern in message", file=sys.stderr)
                if "PASS_TO_PASS:" in message:
                    print(f"Found PASS_TO_PASS pattern in message", file=sys.stderr)
                if "METADATA:" in message:
                    print(f"Found METADATA pattern in message", file=sys.stderr)

                commit_fail, commit_pass, commit_metadata = extract_test_fields(message)
                print(f"Extract returned: FAIL_TO_PASS='{commit_fail}', PASS_TO_PASS='{commit_pass}', METADATA='{commit_metadata}'", file=sys.stderr)

                # Always update if we found values, regardless of previous values
                if commit_fail:
                    fail_to_pass_value = commit_fail
                    print(f"Updated FAIL_TO_PASS from commit message to: '{fail_to_pass_value}'", file=sys.stderr)

                if commit_pass:
                    pass_to_pass_value = commit_pass
                    print(f"Updated PASS_TO_PASS from commit message to: '{pass_to_pass_value}'", file=sys.stderr)

                if commit_metadata and (commit_fail or commit_pass):
                    metadata_value = commit_metadata
                    print(f"Updated METADATA from commit message to: '{metadata_value}'", file=sys.stderr)

                if fail_to_pass_value or pass_to_pass_value:
                    break

    # Convert values to JSON arrays
    fail_to_pass_json = to_json_array(fail_to_pass_value) if fail_to_pass_value else "[]"
    pass_to_pass_json = to_json_array(pass_to_pass_value) if pass_to_pass_value else "[]"

    return fail_to_pass_json, pass_to_pass_json, metadata_value, comment_id

# Function to fetch issue comments
def fetch_issue_comments(organization_repository, issue_number):

    try:
        # Check for test environment variable that provides mocked comments
        test_comments = os.environ.get('TEST_ISSUE_COMMENTS', '')
        if test_comments:
            print(f"Using test issue comments from environment variable", file=sys.stderr)
            # For test comments, we don't have an ID, so use a placeholder
            return [{"id": "test_comment_id", "body": test_comments}]

        if issue_number == 'unknown' or not os.environ.get('GH_TOKEN', ''):
            return []

        cmd = [
            'gh', 'api',
            f'repos/{organization_repository}/issues/{issue_number}/comments',
            '--jq', '.[] | {id: .id, body: .body}'
        ]

        result = run_subprocess(cmd, capture_output=True, text=True, check=True)
        comments_json = result.stdout.strip().split('\n')
        comments = []
        for comment_json in comments_json:
            if comment_json:
                try:
                    comment = json.loads(comment_json)
                    comments.append(comment)
                except json.JSONDecodeError as e:
                    print(f"Error parsing comment JSON: {e}", file=sys.stderr)
        return comments
    except Exception as e:
        print(f"Error fetching issue comments: {e}", file=sys.stderr)
        return []

if __name__ == "__main__":
    try:
        # Process test fields
        fail_to_pass_json, pass_to_pass_json, metadata_value, comment_id = process_test_fields(organization + "/" + repository, issue_number)

        # Output the results
        print(f"fail_to_pass={fail_to_pass_json}")
        print(f"pass_to_pass={pass_to_pass_json}")
        print(f"metadata={metadata_value}")
        print(f"comment_id={comment_id}")
        print("has_error=false")
    except Exception as e:
        print(f"Error extracting test fields: {e}", file=sys.stderr)
        print("fail_to_pass=[]")
        print("pass_to_pass=[]")
        print("metadata=")
        print("comment_id=")
        print("has_error=true")