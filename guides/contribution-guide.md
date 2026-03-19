# EE-Bench Contribution Guide

How to create and submit datapoints for the EE-Bench benchmark.

## Introduction

A **datapoint** is a self-contained evaluation instance — a source PR in a `dpaia/*` repository paired with `.ee-bench/` configuration that defines how to build, run tests, and validate the change. Each datapoint includes a Dockerfile, an evaluation script (`run.sh`), metadata, and expected test outcomes.

Currently the only supported evaluation type is **codegen** (code generation). The pipeline is fully automated: once your PR is added to the project board and moved to "Review", the bot verifies your datapoint, generates a dataset entry, validates it, and merges it — no manual intervention required after the initial review.

**Pipeline overview:**
1. You create a PR in a `dpaia/*` repo with `.ee-bench/codegen/` configuration
2. A reviewer moves the PR to "Review" on the Code Generation project board
3. The bot runs verification and posts results on the PR
4. If verification passes, the reviewer moves the PR to "Verified"
5. The bot generates a dataset PR, validates it, auto-merges it, and closes your source PR

## Prerequisites

- **Repository**: Must be under the `dpaia` GitHub organization
- **Docker**: Required for local testing (`linux/amd64` platform)
- **jq**: Required by the validation script

## Setting Up a Repository

Source PRs must live in a repository under the `dpaia` GitHub organization. If the project you want to create a datapoint for is not already in the org, fork it.
By default, the main branch should be protected from direct pushes.

## Directory Structure

Your repository main branch or PR must include a `.ee-bench/codegen/` directory in the repository root with the following structure:

```
.ee-bench/codegen/
├── metadata.json                # Required: datapoint configuration
├── environment/
│   └── Dockerfile               # Required: builds the test environment
└── eval/
    ├── run.sh                   # Required: evaluation entry point
    └── scripts/                 # Optional: helper scripts used by run.sh
        └── ...
```

### Default-Branch vs PR-Branch Resolution

The export system resolves files from multiple locations with the following priority (highest first):

| Priority | Source                    | Description                                                      |
|----------|---------------------------|------------------------------------------------------------------|
| 1        | `metadata.json` overrides | Fields like `environment.dockerfile` or `environment.files`      |
| 2        | PR branch                 | Files in `.ee-bench/codegen/` on the PR's head commit            |
| 3        | Default branch            | Files in `.ee-bench/codegen/` on the repository's default branch |

This means you can keep shared configuration on the default branch and override specific files per-PR.

## metadata.json

The metadata file defines the datapoint's identity and expected test outcomes.

### Fields

Any fields that are required for the evaluation.

### Common Optional Fields

| Field                           | Type     | Description                                                           |
|---------------------------------|----------|-----------------------------------------------------------------------|
| `version`                       | string   | Schema version (default: `"1.0"`)                                     |
| `benchmark_type`                | string   | Evaluation type (default: `"codegen"`)                                |
| `language`                      | string   | Programming language (e.g., `"java"`, `"csharp"`, `"python"`)         |
| `jvm_version`                   | string   | JVM version if applicable (e.g., `"21"`, `"24"`)                      |
| `test_framework`                | string   | Test framework identifier (e.g., `"net6.0"`, `"junit5"`)              |
| `environment.project_root`      | string   | Working directory inside the container (default: `/repo`)             |
| `environment.docker.run_params` | string   | Extra `docker run` flags (e.g., `"--network=host"`, `"--privileged"`) |
| `expected.fail_to_pass`         | string[] | List of tests which should be fixed                                   |
| `environment.files`             | object   | Map of filename to content, added to the Docker build context         |
| `eval.timeout_seconds`          | number   | Maximum evaluation time in seconds                                    |
| `eval.files`                    | object   | Map of filename to content, added to the eval directory               |

### Example

```json
{
  "version": "1.0",
  "benchmark_type": "codegen",
  "language": "csharp",
  "expected": {
    "fail_to_pass": [
      "Moq.Tests.Regressions.IssueReportsFixture.Issue1259"
    ],
    "pass_to_pass": [
      "Moq.Tests.MatcherAttributeFixture.TypedMatcherDoesNotMismatch"
    ]
  },
  "environment": {
    "project_root": "/repo",
    "docker": {
      "run_params": "--network=host"
    }
  },
  "eval": {
    "timeout_seconds": 600
  }
}
```

### Template Variables in .ee-bench Files

All files in `.ee-bench/codegen/` (Dockerfiles, eval scripts, environment files) are rendered as Jinja2 templates before use. The template context is built in two phases:

**Phase 1 — Built-in fields** (always available):

| Variable                      | Source              | Description                      |
|-------------------------------|---------------------|----------------------------------|
| `{{ instance.repo_url }}`     | PR data             | Repository clone URL             |
| `{{ instance.base_commit }}`  | PR data             | Base commit SHA                  |
| `{{ instance.head_commit }}`  | PR data             | Head commit SHA                  |
| `{{ instance.owner }}`        | Computed            | Repository owner (e.g., `dpaia`) |
| `{{ instance.repo_name }}`    | Computed            | Repository name (e.g., `moq`)    |
| `{{ instance.repo }}`         | Computed            | Full `owner/repo_name`           |
| `{{ instance.instance_id }}`  | PR data or metadata | Datapoint identifier             |
| `{{ instance.project_root }}` | metadata or `/repo` | Working directory in container   |

**Phase 2 — metadata.json fields** (merged after metadata is parsed):

All top-level scalar fields (strings, numbers, booleans, lists) from `metadata.json` are merged into the template context, so any custom field you add becomes available. For example:

```json
{
  "language": "csharp",
  "jvm_version": "21",
  "test_framework": "net6.0"
}
```

Makes `{{ instance.language }}`, `{{ instance.jvm_version }}`, and `{{ instance.test_framework }}` available in all subsequently rendered files.

Built-in fields take precedence — a metadata field will not override a built-in field of the same name.

**Rendering rules:**
- Files without `{{` markers are passed through unchanged
- The `tojson` filter is available for JSON serialization: `{{ instance.expected | tojson }}`
- If rendering fails, the original content is used as-is

## Dockerfile

The Dockerfile sets up the build and test environment. For example:

1. Clone the repository at the specified `base_commit`
2. Install all dependencies needed to build and run tests
3. Target `linux/amd64` platform

### Template Variables

Dockerfiles are rendered as Jinja2 templates. Available variables:

| Variable                      | Description                                         |
|-------------------------------|-----------------------------------------------------|
| `{{ instance.repo_url }}`     | Repository clone URL                                |
| `{{ instance.base_commit }}`  | Base commit SHA                                     |
| `{{ instance.head_commit }}`  | Head commit SHA                                     |
| `{{ instance.owner }}`        | Repository owner                                    |
| `{{ instance.repo_name }}`    | Repository name                                     |
| `{{ instance.repo }}`         | `owner/repo_name`                                   |
| `{{ instance.project_root }}` | Docker working directory (from metadata or `/repo`) |
| `{{ instance.instance_id }}`  | Datapoint identifier                                |
| `{{ instance.<field> }}`      | Any top-level field from metadata.json              |

### Minimal Example

```dockerfile
FROM eclipse-temurin:{{ instance.jvm_version }}

WORKDIR {{ instance.project_root }}

RUN git clone {{ instance.repo_url }} {{ instance.project_root }} && \
    git checkout {{ instance.base_commit }}

# Install dependencies
RUN ./mvnw dependency:go-offline -q

# Clean up .ee-bench to avoid leaking config into the test environment
RUN rm -rf {{ instance.project_root }}/.ee-bench/
```

## eval/run.sh

The evaluation script is the entry point for validation. It receives the patch and evaluation scripts at fixed mount points:

- `/ee-bench/submission/` — contains `patch.diff` (the gold solution or prediction)
- `/ee-bench/eval/` — contains `run.sh` and any helper scripts from `eval/scripts/`

`run.sh` is a validation script, it can:
1. Apply the test patch from `/ee-bench/eval/test_patch.diff`
2. Apply the patch from `/ee-bench/submission/patch.diff`
3. Build the project
4. Run the relevant tests

`run.sh` must return the result Output a JSON result conforming to the result schema v2.0 to stdout.

The validation script identifies the JSON output by searching for a line containing `"schema_version"`. Make sure your script prints exactly one JSON object containing this field to stdout.

### Result Schema v2.0

```json
{
  "schema_version": "2.0",
  "status": "success",
  "duration_seconds": 45.2,
  "criteria": [
    {
      "criterion": "patch_applied",
      "status": "pass",
      "files_modified": ["src/main/java/Example.java"],
      "hunks_applied": 3,
      "hunks_failed": 0
    },
    {
      "criterion": "compilation",
      "status": "pass",
      "exit_code": 0,
      "duration_seconds": 12.1
    },
    {
      "criterion": "tests",
      "status": "pass",
      "summary": {
        "total": 5,
        "passed": 5,
        "failed": 0,
        "skipped": 0
      },
      "passed_tests": [
        { "name": "com.example.FooTest#testBar" }
      ],
      "failed_tests": [],
      "duration_seconds": 8.3
    }
  ]
}
```

**Top-level fields:**

| Field              | Required | Type                     | Description                            |
|--------------------|----------|--------------------------|----------------------------------------|
| `schema_version`   | Yes      | `"2.0"`                  | Must be exactly `"2.0"`                |
| `status`           | Yes      | `"success"` or `"error"` | Whether run.sh completed successfully  |
| `criteria`         | Yes      | array                    | Array of criterion objects             |
| `duration_seconds` | No       | number                   | Total wall-clock time                  |
| `timestamp`        | No       | string                   | ISO-8601 UTC completion time           |
| `error`            | No       | string                   | Error message when status is `"error"` |

**Criterion types:**

| Criterion       | Required Fields                                                  | Description                       |
|-----------------|------------------------------------------------------------------|-----------------------------------|
| `patch_applied` | `criterion`, `status`                                            | Whether the patch applied cleanly |
| `compilation`   | `criterion`, `status`                                            | Whether the project compiles      |
| `tests`         | `criterion`, `status`, `summary`, `passed_tests`, `failed_tests` | Test execution results            |
| `coverage`      | `criterion`, `status`, `metrics`                                 | Code coverage metrics             |

**Criterion status values:** `"pass"`, `"fail"`, `"error"`, `"skip"`

**Test entry fields (for `passed_tests` / `failed_tests`):**

| Field        | Required | Type                                  | Description               |
|--------------|----------|---------------------------------------|---------------------------|
| `name`       | Yes      | string                                | Fully qualified test name |
| `message`    | No       | string                                | Failure/error message     |
| `stacktrace` | No       | string                                | Full stack trace          |
| `type`       | No       | `"assertion"`, `"error"`, `"timeout"` | Failure type              |

**Summary fields:**

| Field     | Required | Type    | Description        |
|-----------|----------|---------|--------------------|
| `total`   | Yes      | integer | Total test count   |
| `passed`  | Yes      | integer | Passed test count  |
| `failed`  | Yes      | integer | Failed test count  |
| `skipped` | No       | integer | Skipped test count |
| `errors`  | No       | integer | Error count        |

## PR Body Format

You can optionally structure your PR description with these recommended headings to help reviewers understand the datapoint:

```markdown
## Problem Statement

Describe what the issue or feature request is about.

## Requirements

List the specific code changes expected from an LLM solving this issue.

## Hints

Optional guidance or context that narrows the solution space.

## Interface

Optional section describing API contracts or function signatures involved.
```

## Submitting

1. Create a branch in the target `dpaia/*` repository
2. Add the `.ee-bench/codegen/` directory with all required files or only files which override defaults from main branch (for example only metadata.json)
3. Open a pull request — the PR itself contains the code change (the "gold patch") that solves the issue
4. Request that the PR be added to the [Code Generation](https://github.com/orgs/dpaia/projects/13) project
5. When PR complete, move to "Review" to begin automated verification

## Pipeline Status Flow

Once your PR is on the project board, here's what happens at each status:

### Review

The bot sets the **Verification** field to "Pending" and dispatches a verification workflow that:
1. Exports a datapoint from your PR using the export script
2. Builds the Docker image from your Dockerfile
3. Runs `run.sh` with the gold patch
4. Posts a comment on your PR with the verification result
5. Sets the **Verification** field to "Passed" or "Failed" based on the result

The comment looks like:

```
✅ Datapoint verification **passed**.

**Instance:** `devlooped__moq-1259`
**Duration:** 45s
**Tests:** Total: 5, Passed: 5, Failed: 0, Skipped: 0
**FAIL_TO_PASS:** Expected: 1, Matched: 1
**Details:** [Workflow run](https://github.com/...)
```

A "Datapoint Verification" check run also appears on the PR's Checks tab.

### Verified

After verification passes (Verification field shows "Passed"), a reviewer moves the PR to "Verified". The bot guards this transition — if Verification is not "Passed", the status is reverted. The bot then:
1. Generates a dataset PR in `dpaia/dataset` with your datapoint
2. Posts a comment on your PR linking to the dataset PR
3. The dataset PR is automatically validated and, if it passes, auto-merged

### Done

Once the dataset PR is merged:
1. Both projects (Code Generation and Dataset Metadata) are set to "Done"
2. Your source PR is closed (not merged) with a comment indicating the pipeline is complete

### New Commits

If you push new commits while the PR is in "Review", "Verified", or "Rejected" status, the bot automatically resets the status to "In progress", resets the Verification field to "Pending", and posts an informational comment. Previous verification results are invalidated and the review process must start over.

## Troubleshooting

| Problem                                    | Cause                                                                                | Fix                                                                                                                    |
|--------------------------------------------|--------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| Docker build fails                         | Missing dependencies, incorrect base image, or template variable errors              | Test locally: `docker build --platform linux/amd64 -t test .ee-bench/codegen/environment/`                             |
| No JSON output from run.sh                 | `run.sh` doesn't print a JSON object containing `"schema_version"` to stdout         | Ensure exactly one line of stdout contains `"schema_version"`. Redirect other output to stderr.                        |
| FAIL_TO_PASS mismatch                      | Test names in `metadata.json` don't match actual test names in `passed_tests` output | Check fully qualified test names. The matcher supports exact match and suffix matching.                                |
| Patch doesn't apply                        | The gold patch (PR diff) doesn't apply cleanly to `base_commit`                      | Verify `base_commit` in `metadata.json` matches the actual merge base of your PR                                       |
| Verification comment shows failures        | One or more criteria in the result JSON have non-pass status                         | Check the "Failed criteria" and "Failed tests" sections in the bot comment. Click the workflow run link for full logs. |
| Status reset to "In progress" unexpectedly | New commits were pushed to the PR                                                    | This is expected behavior — the bot invalidates previous verification when the code changes                            |
