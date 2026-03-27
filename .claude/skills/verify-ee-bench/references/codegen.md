# Codegen Verification

Verify that `.ee-bench/codegen/` configuration builds correctly and tests pass. All template rendering happens inside Docker — no Python or Jinja2 required on the host.

## Prerequisites Check

Before starting, verify:
1. `.ee-bench/codegen/metadata.json` exists
2. `.ee-bench/codegen/environment/Dockerfile` exists
3. `.ee-bench/codegen/eval/run.sh` exists
4. Docker is running: `docker info > /dev/null 2>&1`
5. Current directory is a git repo: `git rev-parse --git-dir > /dev/null 2>&1`

If any check fails, report the specific missing prerequisite and stop.

## Step 1: Collect Template Variables

Gather all values needed to render Jinja2 templates:

```bash
# Git info
BASE_COMMIT=$(git rev-parse HEAD)
REMOTE_URL=$(git remote get-url origin)
# Parse owner/repo from remote URL (handles both HTTPS and SSH)
REPO_FULL=$(echo "$REMOTE_URL" | sed -E 's#(https://github\.com/|git@github\.com:)##' | sed 's/\.git$//')
OWNER=$(echo "$REPO_FULL" | cut -d'/' -f1)
REPO_NAME=$(echo "$REPO_FULL" | cut -d'/' -f2)
```

Read `metadata.json` and extract:
- `environment.project_root` (default: `/repo`)
- All top-level scalar fields (e.g., `jvm_version`, `python_version`, `dotnet_sdk`, `language`)
- `expected.fail_to_pass` and `expected.pass_to_pass` (use as-is from file, typically empty arrays)

Build the template context JSON:

```json
{
  "instance": {
    "repo_url": "<REMOTE_URL>",
    "base_commit": "<BASE_COMMIT>",
    "head_commit": "<BASE_COMMIT>",
    "owner": "<OWNER>",
    "repo_name": "<REPO_NAME>",
    "repo": "<OWNER>/<REPO_NAME>",
    "instance_id": "<REPO_NAME>-verify",
    "project_root": "<from metadata or /repo>",
    "expected": {
      "fail_to_pass": [],
      "pass_to_pass": []
    },
    "<metadata scalar fields>": "<values>"
  }
}
```

Write this JSON to a temp file (e.g., `/tmp/ee-bench-verify/context.json`).

## Step 2: Render Templates in Docker

Copy `.ee-bench/codegen/` to a temp working directory, then render templates using a Python container:

```bash
# Prepare working directory
WORK_DIR=$(mktemp -d /tmp/ee-bench-verify.XXXXXX)
cp -r .ee-bench/codegen/* "$WORK_DIR/"
# Write context.json to work dir
# (write the JSON from Step 1 to $WORK_DIR/context.json)
```

Run the Jinja2 renderer in Docker:

```bash
docker run --rm \
  -v "$WORK_DIR:/work" \
  python:3-slim \
  bash -c '
    pip install -q jinja2 && python3 -c "
import json, os
from pathlib import Path
from jinja2 import Environment, BaseLoader

with open(\"/work/context.json\") as f:
    ctx = json.load(f)

env = Environment(loader=BaseLoader(), keep_trailing_newline=True)

for root, dirs, files in os.walk(\"/work\"):
    for fname in files:
        if fname == \"context.json\":
            continue
        fpath = Path(root) / fname
        content = fpath.read_text()
        if \"{{\" in content:
            tmpl = env.from_string(content)
            rendered = tmpl.render(**ctx)
            fpath.write_text(rendered)
            print(f\"  Rendered: {fpath.relative_to(Path(\"/work\"))}\")
        else:
            print(f\"  Skipped (no templates): {fpath.relative_to(Path(\"/work\"))}\")
"'
```

After rendering, verify no `{{ }}` markers remain in the rendered Dockerfile:

```bash
if grep -r '{{' "$WORK_DIR/environment/Dockerfile" 2>/dev/null; then
  echo "ERROR: Unrendered template variables in Dockerfile"
  # Stop and report failure
fi
```

Print: `Rendering templates... OK`

## Step 3: Build Docker Image

```bash
docker build --platform linux/amd64 \
  -t "ee-bench-verify:$REPO_NAME" \
  -f "$WORK_DIR/environment/Dockerfile" \
  "$WORK_DIR/environment/"
```

If build fails, print the error output and stop with: `Building Docker image... FAILED`

If build succeeds, print: `Building Docker image... OK (tag: ee-bench-verify:<REPO_NAME>)`

## Step 4: Discover Passing Tests

Determine the test command and results location from `metadata.json` `language` field.

**Language detection and commands:**

| Language | Detect build tool | Compile | Test | Results dir |
|----------|-------------------|---------|------|-------------|
| `java` | `mvnw` in Dockerfile → Maven | `./mvnw compile test-compile -q` | `./mvnw test -q` | `/repo/target/surefire-reports/` |
| `java` | `gradlew` in Dockerfile → Gradle | `./gradlew classes testClasses --no-daemon -q` | `./gradlew test --no-daemon` | `/repo/build/test-results/` |
| `python` | — | `pip install -e .` | `python -m pytest --junitxml=/tmp/test-results/results.xml -v` | `/tmp/test-results/` |
| `csharp` | — | `dotnet restore && dotnet build` | `dotnet test --no-build --logger "trx;LogFileName=results.trx"` | `TestResults/` |

For `language: "java"`, scan the rendered Dockerfile for `mvnw` (Maven) or `gradlew` (Gradle) to determine the build tool.

Run the tests inside the built image and copy parser results back:

```bash
docker run --rm --platform linux/amd64 \
  -v "$WORK_DIR/eval/scripts:/ee-bench/scripts:ro" \
  "ee-bench-verify:$REPO_NAME" \
  bash -c '
    cd <PROJECT_ROOT> && \
    <COMPILE_COMMAND> && \
    mkdir -p /tmp/test-results && \
    <TEST_COMMAND> || true && \
    python3 /ee-bench/scripts/parser.py <RESULTS_DIR> 2>/dev/null
  ' > "$WORK_DIR/discovery_results.json"
```

Replace `<PROJECT_ROOT>`, `<COMPILE_COMMAND>`, `<TEST_COMMAND>`, and `<RESULTS_DIR>` with the values from the language table above.

Parse the discovery results to extract passing test names:

```bash
# Extract passing test names from parser output
PASS_TO_PASS=$(cat "$WORK_DIR/discovery_results.json" | \
  docker run --rm -i python:3-slim python3 -c "
import json, sys
data = json.load(sys.stdin)
names = [t['name'] for t in data.get('passed_tests', [])]
print(json.dumps(names))
")
```

Report: `Running tests... OK (N passed, M failed, K skipped)` using the `summary` from the parser output.
Report: `Discovered N pass_to_pass tests`

If no tests pass (0 passed), report a warning but continue — the user may need to fix the Dockerfile or test configuration.

## Step 5: Re-render Templates with Discovered Tests

Update the context JSON with the discovered `pass_to_pass` list:

```bash
# Update context.json with discovered tests
# Set instance.expected.pass_to_pass = <discovered list>
# Keep instance.expected.fail_to_pass = []
```

Re-run the Jinja2 renderer (same Docker command as Step 2) to re-render `run.sh` with the test list baked in.

Verify no `{{ }}` markers remain in the rendered `run.sh`:

```bash
if grep -r '{{' "$WORK_DIR/eval/run.sh" 2>/dev/null; then
  echo "ERROR: Unrendered template variables in run.sh"
fi
```

Print: `Re-rendering with test list... OK`

## Step 6: Run run.sh End-to-End

Execute the full evaluation pipeline:

```bash
mkdir -p "$WORK_DIR/submission"  # empty — no submission patch

docker run --rm --platform linux/amd64 \
  -v "$WORK_DIR/eval:/ee-bench/eval:ro" \
  -v "$WORK_DIR/submission:/ee-bench/submission:ro" \
  "ee-bench-verify:$REPO_NAME" \
  bash /ee-bench/eval/run.sh 2>/dev/null > "$WORK_DIR/run_output.txt"
```

Print: `Running run.sh... OK` (or `FAILED` if the container exits non-zero)

## Step 7: Validate Output

Extract the JSON result line (the line containing `"schema_version"`):

```bash
RESULT_JSON=$(grep '"schema_version"' "$WORK_DIR/run_output.txt")
```

Validate:
1. **Valid JSON** — parse with `jq` or Python
2. **Schema version** — must be `"2.0"`
3. **compilation criterion** — must be `"pass"`
4. **pass_to_pass criterion** — must be `"pass"` (if tests were discovered) or `"skipped"` (if no tests)
5. **No unrendered templates** — check for `{{ }}` in the output

Extract and display criteria:

```
Results:
  compilation:    <status>
  pass_to_pass:   <status> (N/M)
  baseline_tests: <status>
  patch_applied:  <status>
  tests:          <status>
  fail_to_pass:   <status>
```

## Step 8: Cleanup

Remove the Docker image and temp files:

```bash
docker rmi "ee-bench-verify:$REPO_NAME" 2>/dev/null || true
rm -rf "$WORK_DIR"
```

## Final Verdict

If compilation passes AND pass_to_pass passes (or is skipped with 0 tests):
```
VERIFICATION PASSED
```

Otherwise:
```
VERIFICATION FAILED
```

## Error Handling

At each step, if a failure occurs:
1. Print the step name and `FAILED`
2. Print relevant error output (Docker build log, test stderr, etc.)
3. Skip remaining steps
4. Print `VERIFICATION FAILED`
5. Clean up temp files and Docker image