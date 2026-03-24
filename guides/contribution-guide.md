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

For a complete example, see [dpaia/spectre.console#2](https://github.com/dpaia/spectre.console/pull/2) — a C# datapoint where a bug fix (gold patch) and new tests (test patch) are automatically separated from the PR diff.

## Prerequisites

- **Repository**: Must be under the `dpaia` GitHub organization
- **Docker**: Required for local testing (`linux/amd64` platform)
- **jq**: Required by the validation script

## Setting Up a Repository

Source PRs must live in a repository under the `dpaia` GitHub organization. If the project you want to create a datapoint for is not already in the org, fork it.
By default, the main branch should be protected from direct pushes.

## Starter Templates

Complete starter templates are available in [`guides/templates/`](templates/) for the following build systems:

| Template | Language | Build tool | Test runner | Base image |
|----------|----------|------------|-------------|------------|
| [`csharp/`](templates/csharp/) | C# | `dotnet build` | `dotnet test` (TRX) | `mcr.microsoft.com/dotnet/sdk:8.0` |
| [`python/`](templates/python/) | Python | `pip install` | `pytest` (JUnit XML) | `python:3.11-slim` |
| [`gradle/`](templates/gradle/) | Java/Kotlin | `./gradlew` | `./gradlew test` (JUnit XML) | `eclipse-temurin:21` |
| [`maven/`](templates/maven/) | Java | `./mvnw` | `./mvnw test` (Surefire XML) | `eclipse-temurin:21` |

Each template contains a complete `.ee-bench/codegen/` directory (`metadata.json`, `Dockerfile`, `run.sh`, `parser.py`) ready to copy and customize. Replace placeholder values (test project paths, test names, SDK versions) with your project's specifics.

### Generating Configuration with Agents

Instead of copying templates manually, you can use an AI agent to analyze your project and generate `.ee-bench/` configuration automatically.

#### Installing the Skill

The `generate-ee-bench` skill lives in the [infrastructure](https://github.com/dpaia/infrastructure) repository. To make it available in your target repository:

**Option 1 — Symlink (recommended for active contributors):**

```bash
# From your dpaia/* repository root
mkdir -p .claude/skills
ln -s /path/to/infrastructure/.claude/skills/generate-ee-bench .claude/skills/generate-ee-bench
```

**Option 2 — Copy the skill directory:**

```bash
# From your dpaia/* repository root
mkdir -p .claude/skills
cp -r /path/to/infrastructure/.claude/skills/generate-ee-bench .claude/skills/generate-ee-bench
```

**Option 3 — Clone infrastructure alongside your repo:**

```bash
git clone https://github.com/dpaia/infrastructure.git /tmp/ee-bench-infra
mkdir -p .claude/skills
cp -r /tmp/ee-bench-infra/.claude/skills/generate-ee-bench .claude/skills/generate-ee-bench
```

> **Note:** The `.claude/skills/` directory should be added to `.gitignore` — it is local tooling, not part of the datapoint.

#### Using the Skill

Once installed, run Claude Code in your target repository:

1. Navigate to your `dpaia/*` repository
2. Run Claude Code
3. Type `/generate-ee-bench codegen`
4. The skill analyzes your project, detects the build system (C#, Python, Gradle, or Maven), and generates all required files with project-specific values filled in
5. Review the generated files and fill in `expected.fail_to_pass` and `expected.pass_to_pass` test names in `metadata.json`
6. Follow the [Local Testing](#local-testing) steps to verify your setup

For unsupported build systems, use the starter templates above as a base.

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

All fields in `metadata.json` are **optional**. They are populated in the resulting datapoint and become available as **template variables** in `run.sh`, `Dockerfile`, and other `.ee-bench/` files (see [Template Variables in .ee-bench Files](#template-variables-in-ee-bench-files)). You can add any custom fields your templates need (e.g., `python_version`, `dotnet_sdk`, `node_version`).

### Common Fields

| Field                           | Type     | Description                                                                                                                                               |
|---------------------------------|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| `version`                       | string   | Schema version (default: `"1.0"`)                                                                                                                         |
| `benchmark_type`                | string   | Evaluation type (default: `"codegen"`)                                                                                                                    |
| `language`                      | string   | Programming language (e.g., `"java"`, `"csharp"`, `"python"`)                                                                                             |
| `environment.project_root`      | string   | Working directory inside the container (default: `/repo`)                                                                                                 |
| `environment.docker.run_params` | string   | Extra `docker run` flags (e.g., `"--network=host"`, `"--privileged"`)                                                                                     |
| `expected.fail_to_pass`         | string[] | Tests expected to fail before the fix and pass after — used to verify the gold patch fixes the intended issue. Available as template variable in `run.sh` |
| `expected.pass_to_pass`         | string[] | Tests expected to pass both before and after — ensures the fix doesn't break existing functionality. Available as template variable in `run.sh`           |
| `patch.test_patterns`           | string[] | Glob patterns or file paths classified as test files (overrides built-in heuristics). See [How Patches Are Split](#how-patches-are-split)                 |
| `patch.source_patterns`         | string[] | Glob patterns or file paths classified as source files (highest priority override). See [How Patches Are Split](#how-patches-are-split)                   |
| `environment.files`             | object   | Map of filename to content, added to the Docker build context                                                                                             |
| `eval.files`                    | object   | Map of filename to content, added to the eval directory                                                                                                   |

### Example optional fields

| Field                           | Type     | Description                                                                                                                                               |
|---------------------------------|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| `jvm_version`                   | string   | JVM version — useful for JVM-based repositories (Java, Kotlin, Scala). Example: `"21"`, `"24"`                                                            |
| `test_framework`                | string   | Test framework identifier (e.g., `"net6.0"`, `"junit5"`)                                                                                                  |

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
  "test_framework": "net6.0"
}
```

Makes `{{ instance.language }}` and `{{ instance.test_framework }}` available in all subsequently rendered files.

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

## How Patches Are Split

The PR's full diff is **automatically** split into two patches:

- **Gold patch** (`verify/patch.diff`) — source/production code changes. This is what the AI is expected to produce when solving the issue.
- **Test patch** (`eval/test_patch.diff`) — test file changes. Applied by `run.sh` to verify the AI's solution against the expected tests.

The **base commit** is the PR's merge base (the common ancestor of the PR branch and the target branch).

### Classification Rules

Files in the PR diff are classified using the following precedence (highest first):

1. **`patch.source_patterns`** from `metadata.json` — files matching these patterns are always classified as source code, even if they live in a test directory (highest priority)
2. **`patch.test_patterns`** from `metadata.json` — files matching these patterns are always classified as test files
3. **Built-in heuristics** — regex patterns matching paths containing `/test/`, `/tests/`, `/spec/`, `__tests__/`, or filenames matching `*_test.*`, `*Test.*`, `test_*.*`, `*_spec.*`, etc.

Files under `.ee-bench/` are excluded from both patches.

### Pattern Syntax

Both `test_patterns` and `source_patterns` use Python [`fnmatch`](https://docs.python.org/3/library/fnmatch.html) glob syntax, matched against the full file path from the diff (e.g., `src/main/java/Foo.java`):

| Pattern    | Meaning                                  | Example match                        |
|------------|------------------------------------------|--------------------------------------|
| `*`        | Matches everything (including `/`)       | `*.java` → `src/Foo.java`           |
| `?`        | Matches any single character             | `test_?.py` → `test_a.py`           |
| `[seq]`    | Matches any character in *seq*           | `[abc].txt` → `a.txt`               |
| `[!seq]`   | Matches any character not in *seq*       | `[!a].txt` → `b.txt`                |

Each pattern is matched against the **full relative path** from the diff header (the `a/...` path in `diff --git a/path b/path`). Since `*` matches `/` on POSIX, `test/*` matches `test/foo/bar.py`.

**Examples:**

```json
{
  "patch": {
    "test_patterns": [
      "src/test/*",
      "*.Test.cs",
      "test_helpers/*"
    ],
    "source_patterns": [
      "test/fixtures/shared_data.json",
      "tests/conftest.py"
    ]
  }
}
```

Most datapoints don't need overrides — standard project layouts are handled automatically. Use overrides when your project has unconventional test/source locations:

```json
{
  "patch": {
    "test_patterns": ["src/utils/TestHelper.java"],
    "source_patterns": ["test/helpers/shared_util.py"]
  }
}
```

## eval/run.sh

The evaluation script is the entry point for validation. Like the Dockerfile, `run.sh` is rendered as a **Jinja2 template**, so it can use any metadata.json fields as template variables. For example, `{{ instance.expected.fail_to_pass | tojson }}` to embed the expected failing test list directly in the script, or `{{ instance.base_commit }}` to reset to the correct commit.

It receives the patch and evaluation scripts at fixed mount points:

- `/ee-bench/submission/` — contains `patch.diff` (the gold solution or prediction)
- `/ee-bench/eval/` — contains `run.sh` and any helper scripts from `eval/scripts/`

`run.sh` is a validation script, it typically:
1. Applies the test patch from `/ee-bench/eval/test_patch.diff` (see [How Patches Are Split](#how-patches-are-split))
2. Applies the submission patch from `/ee-bench/submission/patch.diff`
3. Builds the project
4. Runs the relevant tests

`run.sh` must output a JSON result conforming to the result schema v2.0 to stdout.

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

### Best Practices

**Dockerfile:**
- Use specific base image tags (e.g., `eclipse-temurin:21`, `mcr.microsoft.com/dotnet/sdk:8.0`) rather than `latest`
- Install dependencies in a separate layer before cloning the repo — speeds up rebuilds
- Always clean up `.ee-bench/` at the end to avoid leaking config into the test environment
- Target `linux/amd64` platform explicitly
- Pre-fetch/cache dependencies (e.g., `./mvnw dependency:go-offline`, `dotnet restore`) so evaluation runs are faster and more reliable
- Avoid downloading large artifacts at eval time — bake them into the image

**run.sh:**
- Apply test patch before submission patch if test patch exists (order matters for some build systems)
- keep in mind that submission patch is optional, so it may not be applied
- Redirect build/test verbose output to stderr or log files — only the JSON result should go to stdout
- Use `set -euo pipefail` for strict error handling
- Use helper scripts in `eval/scripts/` for complex logic (parsing test results, installing dependencies)
- Use template variables for values that change per-datapoint (base commit, project root, expected tests) rather than hardcoding

### Environment Variables

The following environment variables control `run.sh` behavior at runtime:

| Variable           | Default | Description                                                                                                         |
|--------------------|---------|---------------------------------------------------------------------------------------------------------------------|
| `EE_BENCH_RESET`   | unset   | When set to any non-empty value, `run.sh` resets the repository to the base commit (`git reset --hard` + `git clean`) before applying patches. By default, no reset is performed — the container is assumed to already be at the correct state. Set this when re-running evaluations on a previously modified container. |
| `EE_BENCH_PROJECT_ROOT` | `/repo` or `/app` | Override the project working directory inside the container. |

**Example usage:**
```bash
# Run evaluation with repository reset (e.g., re-running on a modified container)
docker run -e EE_BENCH_RESET=1 ...

# Run evaluation without reset (default — container is already at base commit)
docker run ...
```

## PR Body Format

The PR description carries the problem statement and optional metadata fields. The problem statement goes at the top as plain text. Additional fields are wrapped in `<details>` tags with `type="metadata"` and `key="..."` attributes:

```markdown
Describe what the issue or feature request is about.
This is the problem statement — it becomes the `problem_statement` field
in the exported dataset. Any standard markdown is supported here, including
code blocks, links, and even `<details>` blocks without the `type="metadata"`
attribute (e.g. stack traces).

<details type="metadata" key="hints_text"><summary>Hints</summary>

Optional guidance or context that narrows the solution space.

</details>

<details type="metadata" key="interface"><summary>Interface</summary>

Optional section describing API contracts or function signatures involved.

</details>

<details type="metadata" key="requirements"><summary>Requirements</summary>

List the specific code changes expected from an LLM solving this issue.

</details>
```

**How it works:**

- The `key` attribute determines the field name in the exported dataset (e.g. `key="hints_text"` → `hints_text` field)
- The `<summary>` text is the visible caption shown on GitHub (collapsed by default)
- The export pipeline automatically extracts all `<details type="metadata" key="...">` blocks by key — no additional configuration needed
- Everything outside these blocks becomes the `problem_statement` field
- Regular `<details>` blocks (without `type="metadata"`) are preserved as part of the problem statement

**Supported fields:**

| Key            | Caption      | Description                                   |
|----------------|--------------|-----------------------------------------------|
| `hints_text`   | Hints        | Guidance or context that narrows the solution |
| `interface`    | Interface    | API contracts or function signatures involved |
| `requirements` | Requirements | Specific code changes expected                |

You can add custom fields by using any `key` value — they will be extracted automatically.

## Submitting

1. Create a branch in the target `dpaia/*` repository
2. Add the `.ee-bench/codegen/` directory with all required files or only files which override defaults from main branch (for example only metadata.json)
3. Open a pull request — the PR itself contains the code change (the "gold patch") that solves the issue
4. Request that the PR be added to the [Code Generation](https://github.com/orgs/dpaia/projects/13) project
5. When PR complete, move to "Review" to begin automated verification

## Local Testing

Before creating a PR, verify that your `.ee-bench/codegen/` setup produces a working environment — the Docker image builds, tests execute, and the output conforms to the result schema.

### 1. Render Templates

Your Dockerfile and `run.sh` use Jinja2 template variables (`{{ instance.base_commit }}`, `{{ instance.expected.pass_to_pass | tojson }}`, etc.) that are normally resolved by the export pipeline. For local testing, render them manually using this script:

```bash
#!/usr/bin/env bash
# render_templates.sh — render .ee-bench/codegen/ templates for local testing
set -euo pipefail

REPO_URL="$(git remote get-url origin)"
HEAD_COMMIT="$(git rev-parse HEAD)"
PROJECT_ROOT="/repo"

# Read expected tests from metadata.json (if defined)
METADATA=".ee-bench/codegen/metadata.json"
PASS_TO_PASS="[]"
FAIL_TO_PASS="[]"
if [ -f "$METADATA" ]; then
  PASS_TO_PASS=$(jq -c '.expected.pass_to_pass // []' "$METADATA")
  FAIL_TO_PASS=$(jq -c '.expected.fail_to_pass // []' "$METADATA")
fi

OUT_DIR="/tmp/ee-bench-local"
rm -rf "$OUT_DIR"
cp -r .ee-bench/codegen "$OUT_DIR"

# Replace template variables in all files
find "$OUT_DIR" -type f | while read -r file; do
  sed -i.bak \
    -e "s|{{ *instance\.repo_url *}}|${REPO_URL}|g" \
    -e "s|{{ *instance\.base_commit *}}|${HEAD_COMMIT}|g" \
    -e "s|{{ *instance\.head_commit *}}|${HEAD_COMMIT}|g" \
    -e "s|{{ *instance\.project_root *}}|${PROJECT_ROOT}|g" \
    -e "s|{{ *instance\.expected\.pass_to_pass *| *tojson *}}|${PASS_TO_PASS}|g" \
    -e "s|{{ *instance\.expected\.fail_to_pass *| *tojson *}}|${FAIL_TO_PASS}|g" \
    -e "s|{{ *instance\.expected *| *tojson *}}|{\"pass_to_pass\":${PASS_TO_PASS},\"fail_to_pass\":${FAIL_TO_PASS}}|g" \
    "$file"
  rm -f "${file}.bak"
done

echo "Rendered templates in $OUT_DIR"
```

This copies `.ee-bench/codegen/` to `/tmp/ee-bench-local/` and substitutes the most common variables. If your templates use custom metadata fields (e.g., `{{ instance.jvm_version }}`), add corresponding `sed` lines.

### 2. Build the Docker Image

```bash
docker build --platform linux/amd64 -t test-datapoint -f /tmp/ee-bench-local/environment/Dockerfile /tmp/ee-bench-local/environment/
```

### 3. Run Tests (baseline — no patches)

Run `run.sh` without any patches to verify the environment works and all existing tests pass:

```bash
mkdir -p /tmp/ee-bench-local/submission  # empty — no patches to apply

docker run --rm --platform linux/amd64 \
  -v /tmp/ee-bench-local/eval:/ee-bench/eval:ro \
  -v /tmp/ee-bench-local/submission:/ee-bench/submission:ro \
  test-datapoint \
  bash /ee-bench/eval/run.sh
```

Your `run.sh` should handle the case where `/ee-bench/submission/patch.diff` does not exist (submission patch is optional).

### 4. Verify the Output

Check that the output:
- Contains exactly one JSON line with `"schema_version": "2.0"`
- Has `"status": "success"` at the top level
- Includes a `tests` criterion with all tests passing (`"failed": 0`)
- The `passed_tests` array contains the test names you intend to list in `metadata.json` as `pass_to_pass`

If all tests pass and the output conforms to the schema, your `.ee-bench/codegen/` setup is ready. You can now create a branch with your code fix, open a PR, and proceed with the submission workflow.

### 5. Debug Failures

If the build or tests fail, enter the container interactively:

```bash
docker run --rm -it --platform linux/amd64 test-datapoint bash
```

Inside the container, check that dependencies are installed, the repository is cloned at the correct commit, and tests can be run manually.

## Bot Commands

You can trigger the bot manually by mentioning `@dpaia-validator` in a PR comment with one of the following commands:

### `@dpaia-validator validate`

Triggers the verification workflow on the current PR head commit. The bot:
1. Reacts with a :rocket: emoji to acknowledge the command
2. Dispatches the verification workflow
3. Creates a "Datapoint Verification" check run on the PR
4. Posts a comment with the verification result

Use this to re-run verification after pushing fixes, or if the automatic trigger from the project board didn't fire.

### `@dpaia-validator generate`

Triggers the dataset generation workflow. The bot:
1. Checks that a passing "Datapoint Verification" check exists on the current head SHA
2. Dispatches the generation workflow
3. Creates a "Datapoint Generation" check run on the PR
4. Posts a comment linking to the generated dataset PR

Use this to re-trigger generation if it previously failed or wasn't triggered automatically.

> **Note:** Commands are case-insensitive. If both `validate` and `generate` appear in the same comment, `validate` takes priority.

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
