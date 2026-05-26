---
name: create-ee-bench-datapoint-pr
description: Use when creating an EE-bench codegen datapoint PR from a dataset JSON artifact. Triggers when the user asks to create base and solution branches from a datapoint file, generate .ee-bench/codegen/metadata.json, open a PR from solution to base, add labels, or trigger validation for the PR.
---

# Create EE-Bench Datapoint PR

**Announce at start:** "Using create-ee-bench-datapoint-pr skill to prepare base/solution branches and a PR from a datapoint JSON."

## Usage

```
/create-ee-bench-datapoint-pr /path/to/datapoint_1-1.json
```

If the datapoint path is not provided, ask the user for it.

## Read First

- [workflow.md](references/workflow.md) for the end-to-end procedure
- [troubleshooting.md](references/troubleshooting.md) only when branch creation, PR setup, project routing, or verification fails

## Workflow

1. Read the datapoint JSON and derive branch names from the file stem: `<stem>-base` and `<stem>-solution`
2. Work in temporary git worktrees so the user's current branch and uncommitted changes stay untouched
3. Create the `base` branch from `main`, apply `preflight_patch`, and commit it
4. Create the `solution` branch from `base`, apply `reference_patch`, and commit it
5. On `solution` only, add or update `.ee-bench/codegen/metadata.json` by preserving repo-specific scaffold fields and filling datapoint-specific fields from the JSON
6. Validate `metadata.json` against the datapoint before pushing
7. Push both branches
8. Open the PR from `solution` to `base`
9. Set the PR title to `[ee-bench] <id>: <task_type>`
10. Set the PR description to the datapoint `user_prompt`
11. Add labels for the language and `task_type`
12. After the PR is open, add this exact comment on the PR: `@dpaia-validator validate`
13. Confirm `solution` is based on `base`, not on `main`; if not, rebuild `solution` on top of `base` before finishing
14. If automation fails, inspect the workflow run and classify whether the problem is branch shape, metadata mismatch, validator routing, or infrastructure/auth

## Important Rules

- Do not create `base` and `solution` independently from `main`
- Do not modify the user's active dirty branch just to create datapoint branches or repair them
- Prefer exact file paths in `patch.source_patterns` and `patch.test_patterns`
- After opening the PR, always post `@dpaia-validator validate`
