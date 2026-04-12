# Methodgen Evaluation Type

Generate `.ee-bench/methodgen/` configuration for AI-evaluated method implementations. The model receives a repository with a stub method and must produce a working implementation. Evaluation uses tree-sitter AST parsing — no compilation or test execution required.

## Output Structure

```
.ee-bench/methodgen/
├── metadata.json                # Required: datapoint configuration with target method
├── environment/
│   └── Dockerfile               # Required: lightweight image with git + python + tree-sitter
└── eval/
    ├── run.sh                   # Required: thin wrapper invoking Python evaluator
    └── scripts/
        ├── ee_bench_methodgen.py # Shared evaluator (from templates/shared/)
        └── validate_method.py   # Optional: custom validation script
```

`metadata.json`, `Dockerfile`, `run.sh`, and `ee_bench_methodgen.py` are required. `validate_method.py` is optional. All target config lives in `metadata.json` and is baked into `run.sh` via Jinja2 at export time.

**The skill must copy `ee_bench_methodgen.py`** from `guides/templates/shared/scripts/` into `.ee-bench/methodgen/eval/scripts/`. Do NOT generate evaluator code from scratch.

## Criteria

Four criteria, evaluated sequentially:

| # | Criterion | Pass condition | Fail condition | Skip condition |
|---|-----------|---------------|----------------|----------------|
| 1 | `patch_applied` | `git apply` applies the submission patch cleanly | Patch fails to apply | `patch.diff` missing |
| 2 | `syntax_valid` | Patched file parses without errors, target method resolves exactly once | Parse errors, method not found, or multiple matches | `patch_applied` failed |
| 3 | `pattern_checks` | All regex rules pass against their declared scope | Any rule fails | Syntax invalid or no rules defined |
| 4 | `custom_validation` | `validate_method.py` returns all checks passed | Script fails or any check fails | Syntax invalid or script not provided |

**Overall status:** `success` if `patch_applied` passes and all non-skipped criteria pass.

## Step 1: Detect Build System

Check for file markers (first match wins):

| Priority | Marker files | Language |
|----------|-------------|----------|
| 1 | `pom.xml` | Java (Maven) |
| 2 | `build.gradle` or `build.gradle.kts` | Java (Gradle) |
| 3 | `pyproject.toml` or `setup.py` | Python |

The build system determines the language for tree-sitter grammar selection. **No build tools are installed** in the Docker image — methodgen only needs `git`, `python3`, and tree-sitter.

## Step 2: Identify Target Method

Ask the user for or detect:

1. **Target file** — relative path to the Java/Python source file containing the stub
2. **Method signature** — canonical identifier: `methodName(ParamType1,ParamType2)`
   - For Java: strip generics from parameter types (`List<Foo>` → `List`)
   - For Python: use parameter names without `self`/`cls`: `method_name(param1,param2)`
3. **Stub text** — optional display text showing the empty method signature (not used at runtime)
4. **Validation rules** — regex patterns to check against method/body/file text

## Step 3: Template Variables Reference

Files use **Jinja2 templates** rendered before use.

### Built-in Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `{{ instance.owner }}` | PR data | Repository owner |
| `{{ instance.repo_name }}` | PR data | Repository name |
| `{{ instance.base_commit }}` | PR data | Base commit SHA |
| `{{ instance.project_root }}` | metadata | Working directory in container |
| `{{ instance.language }}` | metadata | Programming language |
| `{{ instance.target.file \| tojson }}` | metadata | Target file relative path (JSON string) |
| `{{ instance.target.method_signature \| tojson }}` | metadata | Target method signature (JSON string) |
| `{{ instance.target.validations \| tojson }}` | metadata | Validation rules as JSON array |

## Step 4: Generate Files

### metadata.json

```json
{
  "version": "1.0",
  "benchmark_type": "methodgen",
  "language": "<detected: java|python>",
  "target": {
    "file": "<relative path to target file>",
    "method_signature": "<canonical method signature>",
    "stub": "<optional display text>",
    "validations": [
      {"type": "contains", "scope": "method_text", "pattern": "<regex>"},
      {"type": "not_contains", "scope": "body_text", "pattern": "<regex>"}
    ]
  },
  "environment": {
    "project_root": "/repo"
  }
}
```

**Validation rule types:**
- `contains` — scoped text must match the regex
- `not_contains` — scoped text must NOT match the regex

**Validation scopes:**
- `method_text` — full extracted method declaration + body
- `body_text` — statements inside the method body only
- `file_text` — full patched target file contents

### environment/Dockerfile

Methodgen uses a lightweight Python image — no build tools needed:

```dockerfile
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y build-essential git curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir tree-sitter tree-sitter-<language>

RUN git clone https://github.com/<detected_owner>/<detected_repo>.git /repo
WORKDIR /repo
RUN git checkout {{ instance.base_commit }}

LABEL ee-bench.type="methodgen"
LABEL ee-bench.version="1.0"
RUN rm -rf /repo/.ee-bench/ 2>/dev/null || true
```

**Language grammar packages:**
- Java: `tree-sitter-java`
- Python: `tree-sitter-python`

**Hardcode** owner, repo name, and language grammar in the Dockerfile. Only `{{ instance.base_commit }}` is a Jinja2 variable.

### eval/run.sh

Thin shell wrapper — all logic is in the Python evaluator. Target config from `metadata.json` is baked into a single `--target` JSON arg via Jinja2 at export time:

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${EE_BENCH_PROJECT_ROOT:-/repo}"
EVAL_DIR="/ee-bench/eval"
SUBMISSION_DIR="/ee-bench/submission"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
OVERALL_START=$SECONDS

cd "$PROJECT_ROOT"

CUSTOM_VALIDATOR=""
if [ -f "$EVAL_DIR/scripts/validate_method.py" ]; then
  CUSTOM_VALIDATOR="$EVAL_DIR/scripts/validate_method.py"
fi

python3 "$EVAL_DIR/scripts/ee_bench_methodgen.py" \
  --project-root "$PROJECT_ROOT" \
  --patch "$SUBMISSION_DIR/patch.diff" \
  --target '{"language": {{ instance.language | tojson }}, "target": {"file": {{ instance.target.file | tojson }}, "method_signature": {{ instance.target.method_signature | tojson }}, "validations": {{ instance.target.validations | tojson }}}}' \
  --custom-validator "$CUSTOM_VALIDATOR" \
  --timestamp "$TIMESTAMP" \
  --duration-seconds "$((SECONDS - OVERALL_START))"
```

### eval/scripts/ — Shared evaluator

Copy `ee_bench_methodgen.py` from `guides/templates/shared/scripts/` into `.ee-bench/methodgen/eval/scripts/`. This is the source of truth for evaluation logic. Do NOT generate evaluator code from scratch.

### eval/scripts/validate_method.py (optional)

If the user wants custom validation beyond regex patterns, create a script that:

**Input arguments:**
- `--method-text <path>` — path to temp file with extracted full method text
- `--body-text <path>` — path to temp file with extracted method body text
- `--file <path>` — path to the full patched target file
- `--config <path>` — path to rendered runtime config

**Output:** JSON array to stdout:
```json
[
  {"name": "check_name", "pass": true},
  {"name": "other_check", "pass": false, "detail": "reason"}
]
```

## Step 5: Post-Generation

Report to the user:

1. **What was generated**: List all created files
2. **What to customize**:
   - `target.file` and `target.method_signature` in `metadata.json` — set per datapoint
   - `target.validations` — add regex rules specific to the expected implementation
   - `validate_method.py` — add if custom validation needed beyond regex
3. **PR convention**: PR description should say "Implement method `<method reference>`"
   - Base branch has the stub, head branch has the gold implementation

## Step 6: Verify and Fix

After reporting, automatically run verification if available:

1. **Invoke `/verify-ee-bench methodgen`**
2. **If verification fails**, fix and re-run
3. If verify skill unavailable, point to the contribution guide