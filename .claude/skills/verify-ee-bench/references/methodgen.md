# Methodgen Verification

Verify that `.ee-bench/methodgen/` configuration builds correctly and the evaluator works. All template rendering happens inside Docker.

## Prerequisites Check

Before starting, verify:
1. `.ee-bench/methodgen/metadata.json` exists
2. `.ee-bench/methodgen/environment/Dockerfile` exists
3. `.ee-bench/methodgen/eval/run.sh` exists
4. `.ee-bench/methodgen/eval/scripts/ee_bench_methodgen.py` exists
5. Docker is running: `docker info > /dev/null 2>&1`
6. Current directory is a git repo: `git rev-parse --git-dir > /dev/null 2>&1`

If any check fails, report the specific missing prerequisite and stop.

## Step 1: Collect Template Variables

Gather values for Jinja2 rendering:

```bash
BASE_COMMIT=$(git rev-parse HEAD)
REMOTE_URL=$(git remote get-url origin)
REPO_FULL=$(echo "$REMOTE_URL" | sed -E 's#(https://github\.com/|git@github\.com:)##' | sed 's/\.git$//')
OWNER=$(echo "$REPO_FULL" | cut -d'/' -f1)
REPO_NAME=$(echo "$REPO_FULL" | cut -d'/' -f2)
```

Read `metadata.json` and extract:
- `environment.project_root` (default: `/repo`)
- `language`
- `target.file`, `target.method_signature`, `target.validations`
- All top-level scalar fields

Build template context JSON:

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
    "language": "<from metadata>",
    "target": {
      "file": "<from metadata>",
      "method_signature": "<from metadata>",
      "validations": []
    }
  }
}
```

Write to temp file.

## Step 2: Render Templates in Docker

Copy `.ee-bench/methodgen/` to a temp working directory, then render:

```bash
WORK_DIR=$(mktemp -d /tmp/ee-bench-verify.XXXXXX)
cp -r .ee-bench/methodgen/* "$WORK_DIR/"
```

Run Jinja2 renderer in Docker:

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

Verify no `{{ }}` markers remain in rendered files:

```bash
if grep -r '{{' "$WORK_DIR/environment/Dockerfile" "$WORK_DIR/eval/run.sh" 2>/dev/null; then
  echo "ERROR: Unrendered template variables"
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

If build fails, print error and stop with: `Building Docker image... FAILED`

If build succeeds, print: `Building Docker image... OK (tag: ee-bench-verify:<REPO_NAME>)`

## Step 4: Verify Target Method Exists

Run `run.sh` with an empty patch to verify the target method resolves in the base commit:

```bash
mkdir -p "$WORK_DIR/submission"
echo "" > "$WORK_DIR/submission/patch.diff"

docker run --rm --platform linux/amd64 \
  -v "$WORK_DIR/eval:/ee-bench/eval:ro" \
  -v "$WORK_DIR/submission:/ee-bench/submission:ro" \
  "ee-bench-verify:$REPO_NAME" \
  bash /ee-bench/eval/run.sh > "$WORK_DIR/syntax_check.json"
```

Parse the result — `patch_applied` will be "pass" (empty patch applies) or "skipped", and `syntax_valid` should show whether the target method resolves in the base commit.

Print: `Target method check... <result>`

## Step 5: Run Full Evaluation with Gold Patch

If the head branch has the gold implementation (a real PR scenario), create the gold patch:

```bash
# Generate gold patch from current HEAD vs base
git diff HEAD~1..HEAD -- "$(jq -r '.target.file' .ee-bench/methodgen/metadata.json)" > "$WORK_DIR/submission/patch.diff"
```

If no gold patch is available (verification during generation), skip this step and report:
```
Gold patch test... SKIPPED (no gold implementation available)
```

If gold patch available, run:

```bash
docker run --rm --platform linux/amd64 \
  -v "$WORK_DIR/eval:/ee-bench/eval:ro" \
  -v "$WORK_DIR/submission:/ee-bench/submission:ro" \
  "ee-bench-verify:$REPO_NAME" \
  bash /ee-bench/eval/run.sh > "$WORK_DIR/run_output.txt" 2>/dev/null
```

Print: `Running run.sh... OK`

## Step 6: Validate Output

Extract JSON result:

```bash
RESULT_JSON=$(cat "$WORK_DIR/run_output.txt")
```

Validate:
1. **Valid JSON** — parse with `jq` or Python
2. **Schema version** — must be `"2.0"`
3. **Criteria present** — must have `patch_applied`, `syntax_valid`, `pattern_checks`, `custom_validation`
4. **No unrendered templates** — check for `{{ }}` in the output

Display criteria:

```
Results:
  patch_applied:      <status>
  syntax_valid:       <status>
  pattern_checks:     <status> (N/M rules passed)
  custom_validation:  <status>
```

## Step 7: Cleanup

```bash
docker rmi "ee-bench-verify:$REPO_NAME" 2>/dev/null || true
rm -rf "$WORK_DIR"
```

## Final Verdict

If `patch_applied` passes and `syntax_valid` passes:
```
VERIFICATION PASSED
```

Otherwise:
```
VERIFICATION FAILED
```

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| tree-sitter import error | Missing language grammar package | Add `pip install tree-sitter-<language>` to Dockerfile |
| Target method not found | Wrong `method_signature` in metadata.json | Check method name and parameter types match exactly |
| Multiple matches | Overloaded methods with same parameter types | Use a more specific signature or different target |
| Parse errors | Syntax error in target file | Check the file at `target.file` is valid source code |
| Unrendered `{{ }}` | Missing template variable in context | Check metadata.json has all fields referenced in templates |

## Error Handling

At each step, if a failure occurs:
1. Print the step name and `FAILED`
2. Print relevant error output
3. Skip remaining steps
4. Print `VERIFICATION FAILED`
5. Clean up temp files and Docker image