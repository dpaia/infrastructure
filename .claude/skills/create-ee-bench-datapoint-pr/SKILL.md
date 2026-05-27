---
name: create-ee-bench-datapoint-pr
description: Use when creating or repairing an EE-bench datapoint PR from a dataset JSON artifact. Triggers when the user asks to turn a datapoint file into stacked base and solution branches, generate or verify .ee-bench/codegen/metadata.json, open a PR from solution to base, add required labels, or trigger validator comments.
---

# Create EE-Bench Datapoint PR

**Announce at start:** "Using create-ee-bench-datapoint-pr skill to prepare base/solution branches and a PR from a datapoint JSON."

Use this skill when the task is "take this datapoint JSON and make the benchmark PR correctly."

## Use When

- The user gives a datapoint JSON path and wants the branches and PR created
- The user wants an existing datapoint PR repaired so the branch shape, metadata, labels, or validator trigger match convention
- The user wants `.ee-bench/codegen/metadata.json` created or verified against a datapoint JSON
- The user wants to understand why a datapoint PR failed validation or opened with the wrong diff

## Do Not Use When

- The task is a normal feature PR unrelated to ee-bench datapoints
- The user only wants code changes in the target repository and does not want branches, metadata, or PR setup handled
- The user gives a patch file without a datapoint JSON and expects generic git help instead of benchmark-specific workflow

## Quick Examples

```
/create-ee-bench-datapoint-pr /Users/anna.kharitonova/Work/dataset/gamedev/evals-ue-v1/artifacts/datapoint_1-1.json
```

Expected outcome:

- Create `datapoint_1-1-base` from `base_commit` when the datapoint provides it, otherwise from `main`
- Create `datapoint_1-1-solution` from `datapoint_1-1-base`
- Add `.ee-bench/codegen/metadata.json` on `solution`
- Open PR `datapoint_1-1-solution -> datapoint_1-1-base`

Another example:

- "Repair PR #42 so the solution branch is actually based on the base branch, then re-run validator"

## Read In This Order

1. [workflow.md](references/workflow.md) for the end-to-end procedure and examples
2. [troubleshooting.md](references/troubleshooting.md) only when branch creation, patch application, PR setup, or verification fails

## Required Outcome

By the end of the task, this skill should produce all of the following:

- A `base` branch built from datapoint `base_commit` when present, otherwise from `main`, using `preflight_patch`
- A `solution` branch built from `base` using `reference_patch`
- An explicit instance name: use datapoint `instance_id` when present, otherwise derive a stable fallback from the datapoint file stem
- A valid `.ee-bench/codegen/metadata.json` on `solution`
- A PR from `solution` to `base`
- PR title `[ee-bench] <id>: <task_type>`
- PR description exactly equal to the datapoint `user_prompt`
- Labels for the language and `task_type`
- The PR added to the `Code Generation` GitHub project: `https://github.com/orgs/dpaia/projects/13`
- A PR comment with exactly `@dpaia-validator validate`

## Non-Negotiable Rules

- `solution` must be stacked on `base`; do not create both branches independently from `main`
- If the datapoint JSON includes `base_commit`, create `base` from that commit instead of blindly using `main`
- If the datapoint JSON includes `instance_id`, use it as the instance name; if it does not, derive a deterministic fallback instead of treating that as a hard failure
- Use temporary worktrees when possible so the user's active checkout stays untouched
- Apply `preflight_patch` only to `base`
- Apply `reference_patch` only to `solution`, after `solution` is created from `base`
- Create or update `.ee-bench/codegen/metadata.json` on `solution` only
- After opening the PR, add it to the `Code Generation` GitHub project: `https://github.com/orgs/dpaia/projects/13`
- Do not add `eval_type: codegen` to the PR description unless the user explicitly asks for it
- After the PR is open, always post `@dpaia-validator validate`

## Output Style

- Be explicit about branch ancestry, metadata fields, and PR wiring
- When fixing a broken datapoint PR, explain whether the root cause was branch shape, patch application, metadata mismatch, or GitHub automation/auth
