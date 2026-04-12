# Methodgen Evaluation Type Design

Evaluation type for AI-generated method implementations. The model receives a repository with a stub method and must produce a working implementation.

## Eval Type Identity

- **Name:** `methodgen`
- **PR convention:** PR description says "Implement method `<method reference>`"
- **Data source:** PR where the base branch has the stub and the head branch has the gold implementation. Same export workflow as codegen.
- **V1 source scope:** The submission patch must modify exactly one language source file: `target.file`. Datapoints that modify additional language source files should be rejected during export or verification.

## Criteria

Evaluated sequentially. `patch_applied` runs first. If it fails, all later criteria are skipped. If `syntax_valid` fails, both `pattern_checks` and `custom_validation` are skipped. `pattern_checks` and `custom_validation` run independently after successful syntax validation.

| # | Criterion | Pass condition | Fail condition | Skip condition |
|---|-----------|---------------|----------------|----------------|
| 1 | `patch_applied` | `git apply` applies the submission patch cleanly | Patch fails to apply | `patch.diff` missing |
| 2 | `syntax_valid` | Submission patch applied, patched `target.file` parses without syntax errors, and the target method resolves exactly once | Parse errors in `target.file`, target method not found, or multiple matches | `patch_applied` failed or skipped |
| 3 | `pattern_checks` | All metadata-defined regex rules pass against their declared scope | Any rule fails | `patch_applied` did not pass, syntax invalid, or no rules defined |
| 4 | `custom_validation` | `validate_method.py` returns all checks passed | Script exits non-zero, emits invalid JSON, or any check fails | `patch_applied` did not pass, syntax invalid, or script not provided |

**Overall status:** `success` if `patch_applied` passes and all non-skipped criteria pass, `failure` otherwise.

## metadata.json Schema

```json
{
  "version": "1.0",
  "benchmark_type": "methodgen",
  "language": "java",
  "target": {
    "file": "src/main/java/com/example/service/CommentService.java",
    "method_signature": "findCommentsByFeatureCode(String,int,int)",
    "stub": "public List<CommentDto> findCommentsByFeatureCode(String featureCode, int page, int size) {\n}",
    "validations": [
      {"type": "contains", "scope": "method_text", "pattern": "@Transactional.*"},
      {"type": "contains", "scope": "body_text", "pattern": "PageRequest\\.of.*"},
      {"type": "contains", "scope": "body_text", "pattern": "commentMapper::toDto"},
      {"type": "not_contains", "scope": "body_text", "pattern": "findAll\\(\\)"}
    ]
  },
  "environment": {
    "project_root": "/repo"
  }
}
```

**Field details:**

- `target` — singular method target for V1.
- `target.file` — path to the file containing the stub, relative to project root.
- `target.method_signature` — canonical identifier used at runtime to resolve the target method from the patched file.
- `target.stub` — optional display/problem text for the model or dataset. It is not used for runtime extraction or matching.
- `target.validations` — array of pattern rules for the `pattern_checks` criterion.
- `language` — programming language, used for tree-sitter grammar selection.
- `environment.project_root` — absolute path to the project root inside the Docker container.

## Runtime Config Delivery

The raw `metadata.json` file is not mounted into the evaluation container by the current EE-Bench runtime. Any fields needed during evaluation must be rendered during export into `eval.files` and/or directly into `run.sh` via Jinja templates.

**Recommended runtime file:** `.ee-bench/methodgen/eval/config/target.json`

Example rendered runtime config:

```json
{
  "language": "java",
  "target": {
    "file": "src/main/java/com/example/service/CommentService.java",
    "method_signature": "findCommentsByFeatureCode(String,int,int)",
    "validations": [
      {"type": "contains", "scope": "method_text", "pattern": "@Transactional.*"},
      {"type": "contains", "scope": "body_text", "pattern": "PageRequest\\.of.*"}
    ]
  }
}
```

`run.sh` and `validate_method.py` should consume the rendered runtime config, not the raw `metadata.json`.

## Validation Rules

| Type | Scope | Pattern / Field | Meaning |
|------|-------|-----------------|---------|
| `contains` | `method_text`, `body_text`, or `file_text` | `@Transactional.*` | Scoped text must contain a regex match |
| `not_contains` | `method_text`, `body_text`, or `file_text` | `findAll\(\)` | Scoped text must NOT contain a regex match |
| `test` | — | `test_class`: FQN | Compile project and run test class; pass if all tests pass |

- Patterns are full Python regex (`re.search` with `re.DOTALL` for multiline matching).
- Case-sensitive by default.
- `method_text` = full extracted method declaration and body.
- `body_text` = statements inside the method body only.
- `file_text` = full patched target file contents.
- `test` validation requires build tools in the Dockerfile and `ee_bench_parser_junit.py` in eval/scripts/. The test class source comes from `test_patch.diff`.

## Target Resolution and Extraction

Use AST-first extraction from the patched file, not diff-hunk extraction.

### Resolution flow

1. Apply the submission patch.
2. Parse the patched `target.file` with tree-sitter for the configured language.
3. Resolve `target.method_signature` exactly once in the patched AST.
4. Extract `method_text` and `body_text` from the resolved AST node byte ranges.
5. Optionally confirm that the patch changed text overlapping the resolved target span. This overlap check is a guardrail only; the AST extraction is the source of truth.

`target.stub` is optional display/problem text and is not used for runtime extraction or matching.

## validate_method.py Contract

Optional custom validation script at `eval/scripts/validate_method.py`.

**Input arguments:**

| Arg | Description | Default |
|-----|-------------|---------|
| `--method-text <path>` | Path to temp file containing extracted full method text | required |
| `--body-text <path>` | Path to temp file containing extracted method body text | required |
| `--file <path>` | Path to the full patched target file | required |
| `--config <path>` | Path to rendered runtime config derived from `metadata.json` | required |

**Output:** JSON to stdout:

```json
[
  {"name": "uses_pagination", "pass": true},
  {"name": "uses_mapper", "pass": true, "detail": "found commentMapper::toDto"},
  {"name": "returns_list", "pass": false, "detail": "expected stream().map().toList() pattern"}
]
```

- Criterion passes if all entries have `"pass": true`.
- Exit code `0` = results in stdout.
- Non-zero exit code or invalid JSON = criterion fails with script output captured in the result.

## run.sh Flow

### Approach: Thin shell wrapper + Python evaluator

`run.sh` should remain a thin orchestration layer. All methodgen-specific logic belongs in `ee_bench_methodgen.py`: patch apply result capture, tree-sitter parsing, target resolution, AST extraction, pattern evaluation, optional custom validation, skip propagation, and final JSON emission.

### Steps

```text
1. Setup
   - Read rendered runtime config from /ee-bench/eval/config/target.json
   - Set PROJECT_ROOT, EVAL_DIR, SUBMISSION_DIR
   - Set timestamp and duration tracking

2. Criterion: patch_applied
   - git apply $SUBMISSION_DIR/patch.diff
   - Capture stdout/stderr
   - If it fails, emit patch_applied=fail and skip all later criteria

3. Invoke Python evaluator
   - Parse patched target.file with tree-sitter
   - Resolve target.method_signature exactly once
   - Extract method_text and body_text from the AST
   - Evaluate syntax_valid, pattern_checks, and custom_validation

4. Emit v2.0 JSON result
```

### Simplified `run.sh` template

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${EE_BENCH_PROJECT_ROOT:-/repo}"
EVAL_DIR="/ee-bench/eval"
SUBMISSION_DIR="/ee-bench/submission"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
OVERALL_START=$SECONDS

cd "$PROJECT_ROOT"

python3 "$EVAL_DIR/scripts/ee_bench_methodgen.py" \
  --project-root "$PROJECT_ROOT" \
  --patch "$SUBMISSION_DIR/patch.diff" \
  --config "$EVAL_DIR/config/target.json" \
  --custom-validator "$EVAL_DIR/scripts/validate_method.py" \
  --timestamp "$TIMESTAMP" \
  --duration-seconds "$((SECONDS - OVERALL_START))"
```

## Docker Image

No shared base image. Each datapoint's Dockerfile installs tree-sitter and the appropriate language grammar.

**Required tools in image:**
- `git`
- `python3`
- `pip install tree-sitter` plus a language-specific grammar package such as `tree-sitter-java` or `tree-sitter-python`

**No build tools needed** (Maven, Gradle, dotnet, etc.) because methodgen does not compile or execute tests.

## Result JSON Output

Success:

```json
{
  "schema_version": "2.0",
  "status": "success",
  "timestamp": "2026-04-09T12:00:00Z",
  "duration_seconds": 3,
  "criteria": [
    {
      "criterion": "patch_applied",
      "status": "pass"
    },
    {
      "criterion": "syntax_valid",
      "status": "pass",
      "language": "java",
      "file": "src/main/java/com/example/service/CommentService.java",
      "method_signature": "findCommentsByFeatureCode(String,int,int)"
    },
    {
      "criterion": "pattern_checks",
      "status": "pass",
      "checks": [
        {"pattern": "@Transactional.*", "scope": "method_text", "type": "contains", "pass": true},
        {"pattern": "PageRequest\\.of.*", "scope": "body_text", "type": "contains", "pass": true},
        {"pattern": "findAll\\(\\)", "scope": "body_text", "type": "not_contains", "pass": true}
      ]
    },
    {
      "criterion": "custom_validation",
      "status": "skipped"
    }
  ]
}
```

Failure (patch applies, syntax passes, pattern fails, custom passes):

```json
{
  "schema_version": "2.0",
  "status": "failure",
  "criteria": [
    {
      "criterion": "patch_applied",
      "status": "pass"
    },
    {
      "criterion": "syntax_valid",
      "status": "pass",
      "language": "java",
      "file": "src/main/java/com/example/service/CommentService.java",
      "method_signature": "findCommentsByFeatureCode(String,int,int)"
    },
    {
      "criterion": "pattern_checks",
      "status": "fail",
      "checks": [
        {"pattern": "@Transactional.*", "scope": "method_text", "type": "contains", "pass": true},
        {"pattern": "commentMapper::toDto", "scope": "body_text", "type": "contains", "pass": false}
      ]
    },
    {
      "criterion": "custom_validation",
      "status": "pass",
      "checks": [
        {"name": "uses_pagination", "pass": true},
        {"name": "returns_list", "pass": true}
      ]
    }
  ]
}
```

## Component Map

| Component | Path | Description |
|-----------|------|-------------|
| Eval engine | `guides/templates/shared/scripts/ee_bench_methodgen.py` | Applies patch, resolves target, extracts AST text, evaluates criteria, emits v2.0 JSON |
| Runtime config template | `guides/templates/<lang>/.ee-bench/methodgen/eval/config/target.json` | Rendered subset of `metadata.json` needed at runtime |
| run.sh template | `guides/templates/<lang>/.ee-bench/methodgen/eval/run.sh` | Thin per-language wrapper that invokes the shared Python evaluator |
| metadata.json template | `guides/templates/<lang>/.ee-bench/methodgen/metadata.json` | Per-language placeholder metadata |
| Dockerfile template | `guides/templates/<lang>/.ee-bench/methodgen/environment/Dockerfile` | Installs tree-sitter and the language grammar |
| Export script | `.github/scripts/export/methodgen/export_unified.py` | Reads `.ee-bench/methodgen/`, produces datapoint.json |
| Generate skill ref | `.agents/skills/generate-ee-bench/references/methodgen.md` | AI-assisted config generation instructions |
| Verify skill ref | `.agents/skills/verify-ee-bench/references/methodgen.md` | AI-assisted config verification instructions |
| Skill routing | `.agents/skills/generate-ee-bench/SKILL.md` and `.agents/skills/verify-ee-bench/SKILL.md` | Add `methodgen` row |
| Bot config | `issue-validator-bot/issue-validator-bot/config/eval-projects.yml` | Add `methodgen` entry |
| Workflow config | `.github/config/eval-projects.json` | Add `methodgen` project number |
| GitHub project board | Manual | Create board with Status and Verification fields |

## What's Reused from Codegen

- Result schema v2.0 envelope
- `validate.sh` unchanged
- Export pipeline structure
- PR-based workflow (base = stub, head = gold)
- Bot dispatch mechanism

## What's New

- `ee_bench_methodgen.py` — shared evaluator for methodgen's four criteria
- Rendered runtime config under `eval/config/target.json`
- Tree-sitter syntax validation plus AST-based target resolution and extraction
- Scoped regex-based pattern matching engine
- `validate_method.py` contract for optional custom validation scripts
