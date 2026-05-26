# Workflow

## Inputs to Read From the Datapoint

Read these fields from the dataset JSON:

- `id`
- `task_type`
- `user_prompt`
- `preflight_patch`
- `reference_patch`
- `fail_to_pass_tests`
- `pass_to_pass_tests`

Use the datapoint file stem for branch names:

- `<stem>-base`
- `<stem>-solution`

Example:

- `datapoint_1-1.json` -> `datapoint_1-1-base`, `datapoint_1-1-solution`

## Branch and Commit Procedure

Use temporary git worktrees.

1. Start from `main`
2. Create `<stem>-base`
3. Apply `preflight_patch`
4. Commit the base branch
5. Create `<stem>-solution` from `<stem>-base`
6. Apply `reference_patch`
7. Commit the solution branch

The required branch shape is:

- `main`
- `<stem>-base`
- `<stem>-solution`

`<stem>-solution` must contain `<stem>-base` as an ancestor.

## metadata.json Procedure

Create or update `.ee-bench/codegen/metadata.json` on the `solution` branch only.

Preserve repo-specific scaffold fields already provided by the repository. Fill the datapoint-specific fields from the dataset JSON:

- `benchmark_type`
  Set to `codegen` if it is missing.
- `language`
  Use the repo-specific expected value, for example `cpp` for Unreal C++ repos.
- `expected.fail_to_pass`
  Copy from `fail_to_pass_tests`.
- `expected.pass_to_pass`
  Copy from `pass_to_pass_tests`.
- `patch.source_patterns`
  Use the production-code file paths touched by the datapoint.
- `patch.test_patterns`
  Use the test file paths touched by the datapoint.

Prefer exact file paths over globs when the datapoint touches a small fixed set of files.

## PR Procedure

Open the PR from `solution` to `base`.

PR title:

- `[ee-bench] <id>: <task_type>`

PR description:

- exactly the `user_prompt` from the datapoint JSON

PR labels:

- one language label
- one `task_type` label

Validator trigger:

- after the PR is created, add this exact PR comment:
  `@dpaia-validator validate`

## Validation Before Finishing

Confirm all of the following:

- `metadata.json` matches the datapoint fields that matter for evaluation
- the PR diff is only the delta from `base` to `solution`
- the `solution` branch is stacked on top of `base`
- the PR title, description, labels, and validator comment match the conventions above

## Notes

- In repos where `.ee-bench/codegen/` scaffolding already lives on `main`, the datapoint PR usually needs only the `metadata.json` override on `solution`
- If PR comments cannot be posted because of auth or repo permissions, report that clearly instead of silently skipping it
