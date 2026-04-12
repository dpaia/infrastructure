# Adding a New Evaluation Type

How to extend EE-Bench with a new evaluation type beyond codegen.

## Overview

An **evaluation type** defines a category of software engineering tasks that EE-Bench can assess. Each type has its own criteria for success, its own evaluation scripts, and its own pipeline configuration. Currently the only supported type is **codegen** (code generation), but the system is designed to support additional types such as debugging, refactoring, or migration.

Adding a new evaluation type touches every layer of the system: data repositories, the infrastructure pipeline, the bot, skill references, and GitHub project boards. This guide walks through every touchpoint.

**Prerequisites:**
- Read the [Contribution Guide](contribution-guide.md) for Dockerfile and `run.sh` conventions
- Read the [Evaluation Guide](evaluation-guide.md) for the result schema and validation pipeline
- Familiarity with the existing codegen pipeline (used as the reference implementation throughout)

## Architecture Map

A new evaluation type requires changes across three layers. The diagram below shows every file and system you will touch.

### Data Layer (per-repository)

Each `dpaia/*` source repository contains evaluation configuration under `.ee-bench/<eval_type>/`:

```
.ee-bench/<eval_type>/
├── metadata.json              # Datapoint metadata (criteria, expected outcomes, etc.)
├── environment/
│   └── Dockerfile             # Reproducible build environment
└── eval/
    ├── run.sh                 # Entry point — self-evaluating script
    └── scripts/               # Helper scripts (eval engine, parsers, etc.)
```

### Pipeline Layer (infrastructure repo + bot)

| Component | Path | Purpose |
|-----------|------|---------|
| Export script | `.github/scripts/export/<eval_type>/export_unified.py` | Converts source PRs into portable datapoint records |
| Workflow config | `.github/config/eval-projects.json` | Single source of truth mapping eval_type to project_number |
| Bot config | `issue-validator-bot/issue-validator-bot/config/eval-projects.yml` | Maps eval_type to full pipeline metadata (project, dataset repo, export script) |
| GitHub project board | _(manual, in dpaia org)_ | Tracks datapoint lifecycle: Todo, In progress, Review, Verified, Rejected, Done |

### Tooling Layer (infrastructure repo)

| Component | Path | Purpose |
|-----------|------|---------|
| Generate skill reference | `.claude/skills/generate-ee-bench/references/<eval_type>.md` | Instructions for AI-assisted config generation |
| Verify skill reference | `.claude/skills/verify-ee-bench/references/<eval_type>.md` | Instructions for AI-assisted config verification |
| Generate skill routing | `.claude/skills/generate-ee-bench/SKILL.md` | Routes `/generate-ee-bench <type>` to the correct reference |
| Verify skill routing | `.claude/skills/verify-ee-bench/SKILL.md` | Routes `/verify-ee-bench <type>` to the correct reference |
| Starter templates | `guides/templates/<template>/.ee-bench/<eval_type>/` | Copy-and-customize starting points per language/build system |

## What's Fixed vs. What's Custom

| Aspect | Fixed (all eval types) | Custom (per eval type) |
|--------|------------------------|------------------------|
| Result schema | v2.0 envelope: `schema_version`, `status`, `criteria[]` with `criterion` + `status` fields | Criteria names, count, and semantics |
| Entry points | `run.sh` at `/ee-bench/eval/run.sh`, Dockerfile at `environment/Dockerfile` | What `run.sh` does internally |
| Validation | `validate.sh` parses JSON, checks `schema_version`, counts criteria | Expected criteria and pass conditions |
| Export pipeline | `export_unified.py` reads `.ee-bench/<eval_type>/`, produces `datapoint.json` | Which fields to extract from `metadata.json` |
| Bot routing | Bot reads `eval-projects.yml`, dispatches by `eval_type` | Config entry per type |
| Workflows | `sweep-pipeline-v2.yml` and `on-datapoint-merged_v2.yml` read `eval-projects.json` | Entry in `eval_projects` map |
| Skill dispatch | `SKILL.md` routing tables map type to reference file | Reference file content |

**Key insight:** Each eval type has its own evaluator script in `guides/templates/shared/scripts/`. Codegen uses `ee_bench_eval.py` (hardcoded 6 criteria). Methodgen uses `ee_bench_methodgen.py` (3 criteria with extensible validation rules). A new eval type should create its own evaluator in `shared/scripts/` (e.g., `ee_bench_<type>.py`) — don't fork `ee_bench_eval.py`, write a standalone script that takes CLI args and emits v2.0 JSON to stdout. The evaluator is then copied into each per-template `eval/scripts/` directory.

## Step-by-Step Checklist

### Step 1: Define evaluation criteria

Decide the criteria that determine success for this evaluation type. Each criterion has a name, pass/fail/skipped semantics, and a role in the overall status computation.

**What to do:**
- Choose criterion names (lowercase, underscore-separated)
- Define what pass, fail, and skipped mean for each
- Define the overall status rule (e.g., "all criteria must pass" or "weighted scoring")
- Document the order of evaluation (criteria are evaluated sequentially; a failure may cause downstream criteria to be skipped)

**Must conform to:** Result schema v2.0 — see [Evaluation Guide: Result Schema](evaluation-guide.md#full-result-schema-v20). The output JSON must have `schema_version: "2.0"` and a `criteria` array where each element has at least `criterion` (string) and `status` (`"pass"`, `"fail"`, or `"skipped"`).

**Verification:** Write a sample JSON output by hand and confirm it parses correctly with `jq '.criteria[] | .criterion, .status'`.

### Step 2: Create the export script

Create `.github/scripts/export/<eval_type>/export_unified.py`.

**What to do:**
- Read `.ee-bench/<eval_type>/` from source repositories
- Produce `datapoint.json` with the standard structure (see [Evaluation Guide: Datapoint Record Structure](evaluation-guide.md#datapoint-record-structure))
- Preserve the directory layout: `environment/Dockerfile`, `eval/run.sh`, `eval/scripts/`, `verify/patch.diff`

**Reference:** `.github/scripts/export/codegen/export_unified.py` — the codegen export script. Copy its structure and adjust field extraction for your metadata schema. The core providers (`EEBenchEnvironmentProvider`, `EEBenchCodegenUnifiedGenerator`, `PatchSplitterProvider`) are reusable — pass `benchmark_type="<eval_type>"` to `EEBenchEnvironmentProvider` so it reads `.ee-bench/<eval_type>/` instead of `.ee-bench/codegen/`.

**Verification:** Run the export script against a test repository and confirm the output `datapoint.json` contains all required fields.

### Step 3: Create starter templates

Create templates under `guides/templates/<template>/.ee-bench/<eval_type>/` for each supported language/build system.

**What to do:**
- Create `metadata.json` with fields specific to the new eval type
- Create `environment/Dockerfile` (can often reuse the codegen Dockerfile)
- Create `eval/run.sh` implementing all criteria from Step 1
- Create `eval/scripts/` with the evaluation engine (fork `ee_bench_eval.py` if criteria differ from codegen)

**Reference:** Existing templates in `guides/templates/csharp/`, `guides/templates/python/`, `guides/templates/gradle/`, `guides/templates/maven/`. Each contains a complete `.ee-bench/codegen/` directory.

**Note:** If your criteria differ from codegen's 6 criteria, create a new evaluator script in `guides/templates/shared/scripts/` (e.g., `ee_bench_<type>.py`). Don't fork `ee_bench_eval.py` — write a standalone script. The evaluator is the source of truth for your type's evaluation logic. Copy it into each per-template `eval/scripts/` directory. Also copy any shared parsers (e.g., `ee_bench_parser_junit.py`) if your type needs JUnit XML or TRX parsing.

**Verification:** Copy a template into a test repository, fill in placeholder values, build the Docker image, and run `run.sh` end-to-end.

### Step 4: Create skill reference docs

Create both generate and verify reference files:
- `.claude/skills/generate-ee-bench/references/<eval_type>.md`
- `.claude/skills/verify-ee-bench/references/<eval_type>.md`

**What to do:**
- Follow the structure of `codegen.md` in each references directory
- Document detection logic (how to identify the project type), file specifications, and post-generation/verification guidance
- Include the criteria list and expected `run.sh` behavior

**Reference:** `.claude/skills/generate-ee-bench/references/codegen.md` and `.claude/skills/verify-ee-bench/references/codegen.md`.

**Verification:** Invoke `/generate-ee-bench <eval_type>` and `/verify-ee-bench <eval_type>` in a test repository. Confirm the skill reads the correct reference file and follows its instructions.

### Step 5: Update skill routing tables

Add a row to both `SKILL.md` files so the skills can dispatch to the new reference.

**Files to edit:**
- `.claude/skills/generate-ee-bench/SKILL.md` — add a row to the "Available Evaluation Types" table
- `.claude/skills/verify-ee-bench/SKILL.md` — add a row to the "Available Evaluation Types" table

**What to add (in each file):**

```markdown
| `<eval_type>` | <Short description> | [<eval_type>.md](references/<eval_type>.md) |
```

**Verification:** Run `/generate-ee-bench <eval_type>` and confirm it resolves to the new reference file without falling back to an error.

### Step 6: Add bot config entry

Add the new evaluation type to the bot's configuration file.

**File:** `issue-validator-bot/issue-validator-bot/config/eval-projects.yml`

**What to add:**

```yaml
# Add to the existing projects: list
  - eval_type: <eval_type>
    project_number: <number>       # GitHub project board number (from Step 7)
    dataset_repo: dpaia/dataset    # Target dataset repository (org/repo)
    export_script: export/<eval_type>/export_unified  # Relative to .github/scripts/, no .py
```

**Post-change:** Redeploy the bot so it picks up the new config.

**Verification:** Confirm the bot logs show the new eval type loaded on startup.

### Step 7: Create GitHub project board

This is a manual step performed in the GitHub UI.

**What to do:**
1. Create a new project board in the `dpaia` organization
2. Add a **Status** field (single select) with values: `Todo`, `In progress`, `Review`, `Verified`, `Rejected`, `Done`
3. Add a **Verification** field (single select) with values: `Pending`, `Passed`, `Failed`
4. Note the project number from the URL (e.g., `https://github.com/orgs/dpaia/projects/14` has project number `14`)

**Verification:** Open the project board URL and confirm all fields are present with the correct options.

### Step 8: Register in workflow config

Add the new eval type to the workflow configuration file.

**File:** `.github/config/eval-projects.json`

**What to edit:** Add an entry to the `eval_projects` map:

```json
{
  "organization": "dpaia",
  "dataset_metadata_project": "3",
  "eval_projects": {
    "codegen": "13",
    "<eval_type>": "<project_number>"
  }
}
```

This is the single source of truth read by `sweep-pipeline-v2.yml` and `on-datapoint-merged_v2.yml`.

**Verification:** Run `jq '.eval_projects["<eval_type>"]' .github/config/eval-projects.json` and confirm it returns the project number.

### Step 9: End-to-end test

Run the full pipeline manually to confirm everything works together.

**What to do:**
1. **Generate** — use `/generate-ee-bench <eval_type>` in a test repository to create `.ee-bench/<eval_type>/` configuration
2. **Verify** — use `/verify-ee-bench <eval_type>` to confirm the configuration is valid
3. **Export** — run the export script to produce a `datapoint.json`
4. **Validate** — run `bash .github/scripts/validate.sh <instance_dir>` against the exported datapoint
5. **Confirm JSON** — inspect the JSON output and verify all criteria are present with correct statuses

**Verification:** All 5 sub-steps complete without errors. The final JSON output has `schema_version: "2.0"`, the correct criteria array, and `status: "success"`.

## Worked Example: "debugging" Eval Type

This section walks through all 9 steps for a hypothetical **debugging** evaluation type. A debugging datapoint gives the model a bug report and asks it to reproduce the bug, identify the root cause, and fix it.

### Criteria (Step 1)

The debugging type has 4 criteria:

| Criterion | Pass condition | Fail condition |
|-----------|---------------|----------------|
| `reproduction` | Bug reproduction script exits non-zero (bug is present) | Script exits 0 (bug not reproduced) |
| `root_cause` | Changed files overlap with expected root cause files | No overlap with expected files |
| `fix_applied` | Submission patch applies cleanly | Patch fails to apply |
| `tests_pass` | All tests pass after the fix is applied | Any test fails |

Overall status rule: all 4 criteria must pass.

### metadata.json (Step 3)

```json
{
  "eval_type": "debugging",
  "build_system": "python",
  "project_root": "/repo",
  "bug_report": "Application crashes with IndexError when processing empty lists",
  "reproduction_script": "scripts/reproduce_bug.py",
  "root_cause_files": [
    "src/processor.py",
    "src/utils.py"
  ],
  "expected": {
    "fail_to_pass": ["tests.test_processor.TestProcessor.test_empty_list"],
    "pass_to_pass": ["tests.test_processor.TestProcessor.test_normal_list"]
  }
}
```

### run.sh (Step 3)

```bash
#!/bin/bash
set -uo pipefail

RESULTS_FILE="/tmp/ee_bench_results.json"
START_TIME=$(date +%s)

# Initialize result
cat > "$RESULTS_FILE" <<'INIT'
{
  "schema_version": "2.0",
  "status": "success",
  "criteria": []
}
INIT

add_criterion() {
  local criterion="$1" status="$2"
  local tmp=$(mktemp)
  jq --arg c "$criterion" --arg s "$status" \
    '.criteria += [{"criterion": $c, "status": $s}]' \
    "$RESULTS_FILE" > "$tmp" && mv "$tmp" "$RESULTS_FILE"
}

# --- Criterion 1: reproduction ---
# The reproduction script should fail (exit non-zero) proving the bug exists
cd /repo
if python /ee-bench/eval/scripts/reproduce_bug.py; then
  # Script succeeded = bug NOT reproduced
  add_criterion "reproduction" "fail"
  REPRO_PASSED=false
else
  # Script failed = bug IS present (expected)
  add_criterion "reproduction" "pass"
  REPRO_PASSED=true
fi

# --- Criterion 2: root_cause ---
# Check if the submission modifies the expected root cause files
if [ -f /ee-bench/submission/patch.diff ]; then
  CHANGED_FILES=$(grep '^diff --git' /ee-bench/submission/patch.diff | sed 's|diff --git a/||;s| b/.*||')
  EXPECTED_FILES=$(jq -r '.root_cause_files[]' /ee-bench/eval/metadata_snapshot.json 2>/dev/null || echo "")

  OVERLAP=false
  for expected in $EXPECTED_FILES; do
    for changed in $CHANGED_FILES; do
      if [ "$expected" = "$changed" ]; then
        OVERLAP=true
        break 2
      fi
    done
  done

  if [ "$OVERLAP" = true ]; then
    add_criterion "root_cause" "pass"
  else
    add_criterion "root_cause" "fail"
  fi
else
  add_criterion "root_cause" "skipped"
fi

# --- Criterion 3: fix_applied ---
if [ -f /ee-bench/submission/patch.diff ]; then
  cd /repo
  if git apply /ee-bench/submission/patch.diff; then
    add_criterion "fix_applied" "pass"
    FIX_APPLIED=true
  else
    add_criterion "fix_applied" "fail"
    FIX_APPLIED=false
  fi
else
  add_criterion "fix_applied" "skipped"
  FIX_APPLIED=false
fi

# --- Criterion 4: tests_pass ---
if [ "$FIX_APPLIED" = true ]; then
  cd /repo
  if python -m pytest tests/ --tb=short -q; then
    add_criterion "tests_pass" "pass"
  else
    add_criterion "tests_pass" "fail"
  fi
else
  add_criterion "tests_pass" "skipped"
fi

# Compute overall status
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

FAILED_COUNT=$(jq '[.criteria[] | select(.status == "fail")] | length' "$RESULTS_FILE")
tmp=$(mktemp)
if [ "$FAILED_COUNT" -gt 0 ]; then
  jq --argjson d "$DURATION" '.status = "failure" | .duration_seconds = $d' "$RESULTS_FILE" > "$tmp" && mv "$tmp" "$RESULTS_FILE"
else
  jq --argjson d "$DURATION" '.duration_seconds = $d' "$RESULTS_FILE" > "$tmp" && mv "$tmp" "$RESULTS_FILE"
fi

cat "$RESULTS_FILE"
```

### eval-projects.json entry (Step 8)

```json
{
  "organization": "dpaia",
  "dataset_metadata_project": "3",
  "eval_projects": {
    "codegen": "13",
    "debugging": "14"
  }
}
```

### eval-projects.yml bot config entry (Step 6)

```yaml
# Add to the existing projects: list
  - eval_type: debugging
    project_number: 14
    dataset_repo: dpaia/dataset
    export_script: export/debugging/export_unified
```

### Skill routing table update (Step 5)

In both `.claude/skills/generate-ee-bench/SKILL.md` and `.claude/skills/verify-ee-bench/SKILL.md`, add a row to the "Available Evaluation Types" table:

```markdown
| `debugging` | Debugging — reproduce bug, identify root cause, apply fix | [debugging.md](references/debugging.md) |
```

## Reference: Codegen as Blueprint

Use the codegen implementation as a working reference for every component. The table below links to each file — read it to understand the expected structure, then adapt for your new type.

| Component | Path | What to learn |
|-----------|------|---------------|
| Export script | `.github/scripts/export/codegen/export_unified.py` | How to read `.ee-bench/` and produce `datapoint.json` |
| Generate skill reference | `.claude/skills/generate-ee-bench/references/codegen.md` | Structure of detection logic, file specs, and guidance |
| Verify skill reference | `.claude/skills/verify-ee-bench/references/codegen.md` | Structure of verification procedure |
| Starter templates | `guides/templates/{csharp,python,gradle,maven}/` | Complete `.ee-bench/codegen/` directories per language |
| Shared eval scripts | `guides/templates/shared/scripts/` | `ee_bench_eval.py` and language-specific parsers |
| Workflow config | `.github/config/eval-projects.json` | How eval_type maps to project_number |
| Validation script | `.github/scripts/validate.sh` | How results are parsed and checked |
