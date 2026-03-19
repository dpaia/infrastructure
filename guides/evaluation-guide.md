# EE-Bench Evaluation Guide

How to export datasets and run validation for EE-Bench datapoints.

## Introduction

This guide covers exporting validated datapoints from the dataset repository and running validation locally or in bulk. Currently only the **codegen** (code generation) evaluation type is supported.

Datapoints live in the `dpaia/dataset` repository, organized as `<eval_type>/<repo>/<instance_id>/`. Each instance contains a `datapoint.json`, environment files (including a Dockerfile), evaluation scripts, and the gold patch.

## Exporting via GitHub Actions

The "Export Dataset (v2)" workflow exports datapoints from `dpaia/dataset` as a downloadable artifact.

### Step-by-Step

1. Navigate to the infrastructure repository's **Actions** tab
2. Select **"Export Dataset (v2)"** from the workflow list
3. Click **"Run workflow"**
4. Fill in the inputs (see table below)
5. Wait for the workflow to complete
6. Download the artifact from the workflow run's **Artifacts** section

### Workflow Inputs

| Input | Type | Default | Description |
|-------|------|---------|-------------|
| `eval_type` | string | `codegen` | Eval type directory: `codegen`, `debugging`, or `all` |
| `search_query` | string | _(empty)_ | GitHub search query to filter merged PRs (empty = all merged) |
| `format` | choice | `folders` | Output format: `folders` (directory per instance) or `jsonl` (one JSON object per line) |
| `output_name` | string | `dataset` | Name of the output artifact |
| `organization` | string | `dpaia` | GitHub organization |
| `dataset_repo` | string | `dataset` | Dataset repository name |

## Using search_query

The `search_query` input uses GitHub's pull request search syntax to filter which merged PRs to include. When empty, all datapoints in the dataset repository are exported.

### Examples

| Query | Effect |
|-------|--------|
| _(empty)_ | Export all datapoints |
| `created:>2025-01-01` | Datapoints from PRs created after January 1, 2025 |
| `author:username` | Datapoints from PRs by a specific author |
| `label:priority` | Datapoints from PRs with a specific label |
| `created:2025-01-01..2025-06-30` | Datapoints from PRs created in the first half of 2025 |

The workflow searches merged PRs in `dpaia/dataset`, extracts `instance_id` from each PR's body metadata, and then locates the corresponding datapoint directory on the filesystem. Instance IDs not found in the repository are skipped with a warning.

## Export Artifact Contents

### Manifest

Every export includes a `manifest.json` at the root:

```json
{
  "eval_type": "codegen",
  "format": "folders",
  "search_query": "",
  "dataset_repo_ref": "main",
  "dataset_repo_commit": "abc123def456...",
  "exported_at": "2025-06-15T14:30:00Z",
  "datapoint_count": 42,
  "instance_ids": ["devlooped__moq-1259", "spectreconsole__spectre.console-1708", "..."]
}
```

### Folder Format

When `format=folders`, each instance is a directory:

```
dataset/
├── manifest.json
├── devlooped__moq-1259/
│   ├── datapoint.json
│   ├── environment/
│   │   └── Dockerfile
│   ├── eval/
│   │   ├── run.sh
│   │   └── scripts/
│   └── verify/
│       └── patch.diff
└── spectreconsole__spectre.console-1708/
    └── ...
```

### JSONL Format

When `format=jsonl`, all instances are in a single file with one JSON object per line:

```
dataset/
├── manifest.json
└── dataset.jsonl
```

Each line in the JSONL file is a self-contained JSON object with all file contents inlined under `environment.files`, `eval.files`, and `verify.files`.

## Running Validation

The validation script (`validate.sh`) builds a Docker image from the datapoint's Dockerfile, mounts the evaluation scripts and gold patch, and runs `run.sh` inside the container.

### Requirements

- `jq` — JSON processor
- `docker` — with support for `linux/amd64` platform

### Quick Start

**Folder mode** — validate a single instance directory:

```bash
bash .github/scripts/validate.sh path/to/instance_id/
```

**JSONL mode** — validate a specific instance from a JSONL file:

```bash
bash .github/scripts/validate.sh dataset.jsonl instance_id
```

### What It Does

1. Reads `datapoint.json` from the instance (or extracts from JSONL)
2. Stages evaluation and submission files to a temp directory
3. Builds the Docker image: `docker build --platform linux/amd64 -t <instance_id>:<commit_short> -f environment/Dockerfile environment/`
4. Runs the container with mounted volumes:
   - `/ee-bench/eval/` — evaluation scripts (read-only)
   - `/ee-bench/submission/` — gold patch (read-only)
   - Additional `docker run` params from `datapoint.json` (`environment.docker.run_params`)
5. Executes: `bash /ee-bench/eval/run.sh`
6. Parses JSON output (looks for a line containing `"schema_version"`)
7. Verifies FAIL_TO_PASS expectations if defined
8. Exits 0 on success (all tests pass), 1 on failure

### Output

```
Building image devlooped__moq-1259:eef6e1b8f968 ...
Running validation ...
Results: 5/5 passed, 0 failed
FAIL_TO_PASS check: all 1 expected tests found in passed_tests

JSON output:
{
  "schema_version": "2.0",
  "status": "success",
  ...
}
```

## Manual Validation

If you need finer control or want to debug issues, follow this step-by-step Docker walkthrough:

### Step 1: Read Metadata

```bash
INSTANCE_DIR="path/to/instance_id"
cat "$INSTANCE_DIR/datapoint.json" | jq .

# Extract key values
INSTANCE_ID=$(jq -r '.instance_id' "$INSTANCE_DIR/datapoint.json")
BASE_COMMIT=$(jq -r '.base_commit' "$INSTANCE_DIR/datapoint.json")
COMMIT_SHORT="${BASE_COMMIT:0:12}"
```

### Step 2: Build Docker Image

```bash
docker build --platform linux/amd64 \
  -t "${INSTANCE_ID}:${COMMIT_SHORT}" \
  -f "$INSTANCE_DIR/environment/Dockerfile" \
  "$INSTANCE_DIR/environment/"
```

### Step 3: Prepare Staging Directory

```bash
STAGE_DIR="/tmp/ee-bench-validate-${INSTANCE_ID}"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/eval" "$STAGE_DIR/submission"

cp -r "$INSTANCE_DIR/eval/"* "$STAGE_DIR/eval/"
cp -r "$INSTANCE_DIR/verify/"* "$STAGE_DIR/submission/"
```

### Step 4: Run Container

```bash
# Read optional docker run params
DOCKER_RUN_PARAMS=$(jq -r '.environment.docker.run_params // empty' "$INSTANCE_DIR/datapoint.json")

# Run with gold patch mounted
docker run --rm --platform linux/amd64 \
  -v "$STAGE_DIR/eval":/ee-bench/eval:ro \
  -v "$STAGE_DIR/submission":/ee-bench/submission:ro \
  $DOCKER_RUN_PARAMS \
  "${INSTANCE_ID}:${COMMIT_SHORT}" \
  bash /ee-bench/eval/run.sh
```

### Step 5: Interpret Output

Look for the JSON output line containing `"schema_version"`. Parse it with jq:

```bash
# Capture output
OUTPUT=$(docker run --rm --platform linux/amd64 \
  -v "$STAGE_DIR/eval":/ee-bench/eval:ro \
  -v "$STAGE_DIR/submission":/ee-bench/submission:ro \
  $DOCKER_RUN_PARAMS \
  "${INSTANCE_ID}:${COMMIT_SHORT}" \
  bash /ee-bench/eval/run.sh 2>&1)

# Extract JSON
JSON=$(echo "$OUTPUT" | grep '"schema_version"')
echo "$JSON" | jq .
```

### Step 6: Debug Failures

If the container fails, run it interactively:

```bash
docker run --rm -it --platform linux/amd64 \
  -v "$STAGE_DIR/eval":/ee-bench/eval:ro \
  -v "$STAGE_DIR/submission":/ee-bench/submission:ro \
  $DOCKER_RUN_PARAMS \
  "${INSTANCE_ID}:${COMMIT_SHORT}" \
  bash
```

Inside the container:
- Check that the patch applies: `cd /repo && git apply /ee-bench/submission/patch.diff`
- Run the build manually
- Run individual tests to isolate failures

### Step 7: Clean Up

```bash
rm -rf "$STAGE_DIR"
docker rmi "${INSTANCE_ID}:${COMMIT_SHORT}"
```

## Understanding Results

The JSON output from `run.sh` follows the result schema v2.0. Here's how to interpret it:

### Top-Level Fields

| Field | Values | Meaning |
|-------|--------|---------|
| `status` | `"success"` | `run.sh` completed without errors (individual criteria may still fail) |
| `status` | `"error"` | `run.sh` encountered an error; check the `error` field |
| `duration_seconds` | number | Total wall-clock time for the run |

### Criteria Array

The `criteria` array contains one object per evaluated aspect. The primary criterion for codegen is `tests`.

**Tests criterion:**

```json
{
  "criterion": "tests",
  "status": "pass",
  "summary": {
    "total": 10,
    "passed": 10,
    "failed": 0,
    "skipped": 0
  },
  "passed_tests": [
    { "name": "com.example.FooTest#testBar" }
  ],
  "failed_tests": []
}
```

- `summary.total` / `summary.passed` / `summary.failed` — test counts
- `passed_tests[].name` — fully qualified names of passing tests (used to verify FAIL_TO_PASS expectations)
- `failed_tests[].name` — names of failing tests, with optional `message`, `stacktrace`, and `type` fields

**Other criteria:**

| Criterion | Key Fields | Description |
|-----------|-----------|-------------|
| `patch_applied` | `files_modified`, `hunks_applied`, `hunks_failed` | Whether the gold patch applied cleanly |
| `compilation` | `exit_code`, `error_message`, `duration_seconds` | Whether the project compiled |
| `coverage` | `metrics.line_coverage_pct`, `metrics.branch_coverage_pct` | Code coverage (optional) |

### Full Result Schema v2.0

```json
{
  "schema_version": "2.0",
  "status": "success | error",
  "timestamp": "ISO-8601 (optional)",
  "duration_seconds": 45.2,
  "criteria": [
    {
      "criterion": "patch_applied",
      "status": "pass | fail | error | skip",
      "files_modified": ["path/to/file.java"],
      "hunks_applied": 3,
      "hunks_failed": 0
    },
    {
      "criterion": "compilation",
      "status": "pass | fail | error | skip",
      "exit_code": 0,
      "error_message": "string (optional)",
      "duration_seconds": 12.1
    },
    {
      "criterion": "tests",
      "status": "pass | fail | error | skip",
      "summary": {
        "total": 10,
        "passed": 10,
        "failed": 0,
        "skipped": 0,
        "errors": 0
      },
      "passed_tests": [
        {
          "name": "fully.qualified.TestName",
          "duration_seconds": 0.5
        }
      ],
      "failed_tests": [
        {
          "name": "fully.qualified.TestName",
          "message": "assertion failure message",
          "stacktrace": "full stack trace",
          "type": "assertion | error | timeout"
        }
      ],
      "duration_seconds": 8.3
    },
    {
      "criterion": "coverage",
      "status": "pass | fail",
      "metrics": {
        "line_coverage_pct": 85.2,
        "branch_coverage_pct": 75.0,
        "function_coverage_pct": 90.0
      }
    }
  ],
  "stdout": "captured output (optional)",
  "stderr": "captured errors (optional)",
  "error": "error message when status is error (optional)"
}
```

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Docker build fails | Missing dependencies, wrong base image, or template rendering errors | Check the Dockerfile for invalid template variables. Build locally with `docker build --platform linux/amd64` |
| No JSON output from run.sh | Script doesn't print a line containing `"schema_version"` to stdout | Ensure `run.sh` outputs exactly one JSON object with `"schema_version": "2.0"`. Redirect build/test output to stderr or a file. |
| FAIL_TO_PASS mismatch | Test names in `expected.FAIL_TO_PASS` don't match `passed_tests[].name` in the result | Verify fully qualified test names. The matcher checks exact match, prefix match, and suffix match. |
| Patch application failure | Gold patch doesn't apply to the codebase at `base_commit` | Check that `base_commit` is correct and that `patch.diff` in `verify/` was generated from that base |
| Compilation failure | Build tools or dependencies missing in Docker image | Enter the container interactively (`docker run --rm -it ... bash`) and debug the build |
| Validation passes locally but fails in CI | Environment differences (network, platform, caching) | Ensure `--platform linux/amd64` is set. Check if `docker.run_params` includes network flags. |

## Bulk Validation

To validate all instances in a folder-format export:

```bash
#!/usr/bin/env bash
set -euo pipefail

EXPORT_DIR="${1:?Usage: $0 <export_dir>}"
PASSED=0
FAILED=0
ERRORS=()

for INSTANCE_DIR in "$EXPORT_DIR"/*/; do
  [ -f "$INSTANCE_DIR/datapoint.json" ] || continue

  INSTANCE_ID=$(jq -r '.instance_id' "$INSTANCE_DIR/datapoint.json")
  echo "=== Validating: $INSTANCE_ID ==="

  if bash .github/scripts/validate.sh "$INSTANCE_DIR"; then
    PASSED=$((PASSED + 1))
  else
    FAILED=$((FAILED + 1))
    ERRORS+=("$INSTANCE_ID")
  fi

  echo ""
done

echo "=== Summary ==="
echo "Passed: $PASSED"
echo "Failed: $FAILED"
if [ ${#ERRORS[@]} -gt 0 ]; then
  echo "Failed instances:"
  printf '  - %s\n' "${ERRORS[@]}"
fi
```

To validate instances from a JSONL export:

```bash
#!/usr/bin/env bash
set -euo pipefail

JSONL_FILE="${1:?Usage: $0 <dataset.jsonl>}"
PASSED=0
FAILED=0
ERRORS=()

while IFS= read -r line; do
  INSTANCE_ID=$(echo "$line" | jq -r '.instance_id')
  [ -z "$INSTANCE_ID" ] && continue

  echo "=== Validating: $INSTANCE_ID ==="

  if bash .github/scripts/validate.sh "$JSONL_FILE" "$INSTANCE_ID"; then
    PASSED=$((PASSED + 1))
  else
    FAILED=$((FAILED + 1))
    ERRORS+=("$INSTANCE_ID")
  fi

  echo ""
done < "$JSONL_FILE"

echo "=== Summary ==="
echo "Passed: $PASSED"
echo "Failed: $FAILED"
if [ ${#ERRORS[@]} -gt 0 ]; then
  echo "Failed instances:"
  printf '  - %s\n' "${ERRORS[@]}"
fi
```
