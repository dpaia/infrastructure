# Reusable Workflow: Run Tests Maven

This document explains how to use the reusable `run-tests-maven` workflow from other repositories in the organization.

## Overview

The `run-tests-maven` workflow is a reusable GitHub Actions workflow that can be invoked from other repositories. It performs the following tasks:

1. Extracts test names from issue descriptions, PR comments, or issue comments
2. Creates a placeholder comment on the issue
3. Sets up Java and Maven
4. Runs Maven tests
5. Updates the issue comment with the final status

The workflow can be triggered in two ways:
1. As a reusable workflow called from another workflow
2. Automatically when a new comment is added to an issue that contains FAIL_TO_PASS or PASS_TO_PASS markers

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