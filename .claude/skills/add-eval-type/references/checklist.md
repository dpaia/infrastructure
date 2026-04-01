# Add Eval Type — File Checklist

Exact paths for all files that must be created or modified when adding a new evaluation type.
`<eval_type>` is the lowercase name (e.g., `debugging`).
`<template>` is the language/build-system name (e.g., `python`, `maven`).

## Files to Create

| File | Source/Reference |
|------|------------------|
| `.github/scripts/export/<eval_type>/export_unified.py` | Adapt from `.github/scripts/export/codegen/export_unified.py` |
| `guides/templates/<template>/.ee-bench/<eval_type>/metadata.json` | Adapt from `guides/templates/<template>/.ee-bench/codegen/metadata.json` |
| `guides/templates/<template>/.ee-bench/<eval_type>/environment/Dockerfile` | Adapt from `guides/templates/<template>/.ee-bench/codegen/environment/Dockerfile` |
| `guides/templates/<template>/.ee-bench/<eval_type>/eval/run.sh` | Write from scratch using criteria definitions |
| `guides/templates/<template>/.ee-bench/<eval_type>/eval/scripts/` | Custom eval emitter; optionally copy parsers from `guides/templates/shared/scripts/` |
| `.claude/skills/generate-ee-bench/references/<eval_type>.md` | Follow structure of `references/codegen.md` |
| `.claude/skills/verify-ee-bench/references/<eval_type>.md` | Follow structure of `references/codegen.md` |

## Files to Modify

| File | Change |
|------|--------|
| `.claude/skills/generate-ee-bench/SKILL.md` | Add row to "Available Evaluation Types" table |
| `.claude/skills/verify-ee-bench/SKILL.md` | Add row to "Available Evaluation Types" table |
| `.github/config/eval-projects.json` | Add `"<eval_type>": "<project_number>"` to `eval_projects` |

## External / Manual Changes

| System | Change |
|--------|--------|
| GitHub Projects | Create project board in `dpaia` org with status + verification fields |
| `issue-validator-bot/issue-validator-bot/config/eval-projects.yml` | Add eval_type entry with project_number, dataset_repo, export_script |
| Bot deployment | Redeploy after config change |
