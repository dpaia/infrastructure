# Reusable Workflow: Run Tests Maven

This document explains how to use the reusable `run-tests-maven` workflow from other repositories in the organization.

## Overview

The `run-tests-maven` workflow is a reusable GitHub Actions workflow that can be invoked from other repositories. It performs the following tasks:

1. Collects issue numbers based on the event type (pull request, commit, or issue comment)
2. Extracts test names from issue descriptions, PR comments, or issue comments using a matrix strategy for parallel processing
3. Combines results from multiple issues
4. Creates a placeholder comment on the issue (for push or issue comment events only)
5. Sets up Java and Maven
6. Runs Maven tests
7. Updates the issue comment with the final status (for push or issue comment events only)

The workflow can be triggered in three ways:
1. As a reusable workflow called from another workflow
2. Automatically when a new comment is added to an issue that contains FAIL_TO_PASS or PASS_TO_PASS markers
3. When a commit is pushed or a pull request is created

## Workflow Architecture

The workflow is structured as a series of jobs with dependencies:

1. **collect-issues**: Extracts issue numbers based on the event type
2. **extract-tests**: Uses a matrix strategy to process each issue number in parallel, extracting FAIL_TO_PASS and PASS_TO_PASS values
3. **combine-results**: Combines the results from all issues processed in the matrix
4. **check-tests**: Verifies that FAIL_TO_PASS or PASS_TO_PASS values were found (for pull requests)
5. **placeholder-comment**: Creates a placeholder comment on the issue (for push or issue comment events)
6. **run-tests**: Executes the Maven tests
7. **update-comment**: Updates the issue comment with the final status (for push or issue comment events)

This job-based architecture allows for better parallelization and more efficient processing, especially when dealing with multiple issues.

### Event-Specific Behavior

The workflow behaves differently depending on the event type:

#### Pull Request Event
When triggered by a pull request, it:
1. Collects issue numbers from all linked commits in the PR
2. Uses a matrix strategy to process each issue number in parallel:
   - Each issue is processed independently in its own job
   - Test names are extracted from issue descriptions, comments, and linked commits
   - Results are stored as artifacts
3. Combines the results from all issues:
   - Downloads and processes all artifacts
   - Merges the FAIL_TO_PASS and PASS_TO_PASS values from all issues
   - Keeps the latest values for each test
4. Verifies that at least one FAIL_TO_PASS or PASS_TO_PASS value was found

This parallel processing approach is more efficient, especially when dealing with multiple issues. It allows you to reference multiple issues in your PR commits and have all their test requirements combined, while processing them simultaneously.

#### Push Event
When triggered by a push event, it:
1. Uses the issue number from the commit event
2. Creates a placeholder comment on the issue
3. Runs the tests and updates the comment with the final status

#### Issue Comment Event
When triggered by an issue comment event, it:
1. Uses the issue number from the comment event
2. Creates a placeholder comment on the issue
3. Runs the tests and updates the comment with the final status

## How to Use

To use this reusable workflow in your repository, create a workflow file (e.g., `.github/workflows/run-tests.yml`) with the following content:

```yaml
name: Run Tests

on:
  push:
    branches: [ "main", "your-branches" ]
  pull_request:
    branches: [ "main", "your-branches" ]
  issue_comment:
    types: [created]  

jobs:
  run-tests:
    uses: your-organization/infrastructure/.github/workflows/shared-run-tests-maven.yml@main        
    if: ${{ github.event_name != 'issue_comment' || contains(github.event.comment.body, 'FAIL_TO_PASS') || contains(github.event.comment.body, 'PASS_TO_PASS') }}
    with:
      # Optional: Java version to use (default: '24')
      java-version: '24'
      # Optional: Java distribution to use (default: 'temurin')
      distribution: 'temurin'
      # Optional: Path to the pom.xml file (default: 'pom.xml')
      pom-file: 'pom.xml'
      # Optional: Issue number to extract test names from
      # If not provided, will try to extract from PR or commit message
      issue-number: ''
    secrets:
      # Required: GitHub token for API access
      github-token: ${{ secrets.GITHUB_TOKEN }}
```

## Parameters

### Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `java-version` | Java version to set up | No | `24` |
| `distribution` | Java distribution to use | No | `temurin` |
| `pom-file` | Path to the pom.xml file | No | `pom.xml` |
| `issue-number` | Issue number to extract test names from | No | `` |

### Secrets

| Name | Description | Required |
|------|-------------|----------|
| `github-token` | GitHub token for API access | Yes |

## Requirements

The repository using this workflow must have the following structure:

1. A Maven project with a pom.xml file
2. Tests that can be run with Maven

## Example Usage

### Basic Usage

```yaml
jobs:
  run-tests:
    uses: your-organization/infrastructure/.github/workflows/shared-run-tests-maven.yml@main
    secrets:
      github-token: ${{ secrets.GITHUB_TOKEN }}
```

### Custom Java Version and POM File

```yaml
jobs:
  run-tests:
    uses: your-organization/infrastructure/.github/workflows/shared-run-tests-maven.yml@main
    with:
      java-version: '17'
      pom-file: 'custom/path/to/pom.xml'
    secrets:
      github-token: ${{ secrets.GITHUB_TOKEN }}
```

### Specifying an Issue Number

```yaml
jobs:
  run-tests:
    uses: your-organization/infrastructure/.github/workflows/shared-run-tests-maven.yml@main
    with:
      issue-number: '123'
    secrets:
      github-token: ${{ secrets.GITHUB_TOKEN }}
```

### Automatic Triggering from Issue Comments

The workflow will automatically run when a new comment is added to an issue that contains FAIL_TO_PASS or PASS_TO_PASS markers. For example, if someone adds a comment like:

```
FAIL_TO_PASS: org.example.TestClass#testMethod1, org.example.TestClass#testMethod2
```

The workflow will automatically extract the test names and run them. No additional configuration is needed for this functionality.