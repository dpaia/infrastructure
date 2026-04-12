---
name: add-eval-type
description: Use when adding a new evaluation type to the EE-Bench system. Triggers when user asks to "add eval type", "new evaluation type", "create eval type", or "support new evaluation".
---

# Add New Evaluation Type

**Announce at start:** "Using add-eval-type skill to scaffold a new evaluation type."

## Usage

```
/add-eval-type <eval_type_name>
```

If no name provided, ask the user.

## Prerequisite

Read the full guide before starting: `guides/new-eval-type-guide.md`

## Workflow

### 1. Gather Requirements

Ask the user for:
- **Eval type name** — lowercase, underscore-separated (e.g., `debugging`, `code_review`)
- **Criteria definitions** — for each criterion: name, pass/fail/skipped semantics
- **Overall status rule** — which criteria must pass for overall `"success"`
- **Language/build system** — for the initial starter template

### 2. Scaffold Export Script

- Read the codegen export script first: `.github/scripts/export/codegen/export_unified.py`
- Create `.github/scripts/export/<eval_type>/export_unified.py`
- Adapt the codegen structure: change `.ee-bench/codegen/` references to `.ee-bench/<eval_type>/`
- Keep the same CLI interface and output format

### 3. Scaffold Starter Template

- Ask which language/build system to start with
- Read the closest existing template from `guides/templates/{python,maven,gradle,csharp}/`
- Create `guides/templates/<template>/.ee-bench/<eval_type>/` with:
  - `metadata.json` — include `benchmark_type: "<eval_type>"` and type-specific fields
  - `environment/Dockerfile` — adapt from closest existing template
  - `eval/run.sh` — implement the criteria from step 1
  - `eval/scripts/` — write a custom eval emitter if criteria differ from codegen's 6; copy parsers from `guides/templates/shared/scripts/` if the type uses JUnit XML or TRX output

### 4. Create Skill Reference Docs

- Read the codegen references first:
  - `.Codex/skills/generate-ee-bench/references/codegen.md`
  - `.Codex/skills/verify-ee-bench/references/codegen.md`
- Create `.Codex/skills/generate-ee-bench/references/<eval_type>.md`
  - Cover: detection logic, file specs, metadata.json fields, post-generation steps
- Create `.Codex/skills/verify-ee-bench/references/<eval_type>.md`
  - Cover: prerequisite checks, template rendering, Docker build/test, output validation

### 5. Update Skill Routing Tables

Add a row to the "Available Evaluation Types" table in:
- `.Codex/skills/generate-ee-bench/SKILL.md`
- `.Codex/skills/verify-ee-bench/SKILL.md`

Format:
```markdown
| `<eval_type>` | <Short description> | [<eval_type>.md](references/<eval_type>.md) |
```

### 6. Register in Workflow Config

Update `.github/config/eval-projects.json` — add the eval_type → project_number entry.

If the project number is not known yet, use a placeholder value and print a reminder to update it.

### 7. Manual Steps Reminder

Print clearly:

```
MANUAL STEPS REQUIRED:

[ ] Create GitHub project board in dpaia organization
    - Note the project number
    - Add status fields: Todo, In progress, Review, Verified, Rejected, Done
    - Add Verification field: Pending, Passed, Failed

[ ] Add entry to issue-validator-bot config:
    File: issue-validator-bot/issue-validator-bot/config/eval-projects.yml
    Entry:
      - eval_type: <eval_type>
        project_number: <from step above>
        dataset_repo: dpaia/dataset
        export_script: export/<eval_type>/export_unified

[ ] Redeploy the issue-validator-bot after config change

[ ] Verify .github/config/eval-projects.json has the correct
    project_number (update if placeholder was used)
```

### 8. Verify (if test repo available)

Run `/verify-ee-bench <eval_type>` on the current repo and report results.

### 9. Summary

Print:
- All files created/modified
- All manual steps remaining
- Link to `guides/new-eval-type-guide.md` for full context
