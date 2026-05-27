# Workflow

## What You Read From the Datapoint

Read these fields from the dataset JSON:

- `id`
- `instance_id` when present
- `task_type`
- `user_prompt`
- `base_commit` when present
- `preflight_patch`
- `reference_patch`
- `fail_to_pass_tests`
- `pass_to_pass_tests`

Read additional fields only if the repo expects them. Do not invent missing datapoint fields.

Derive branch names from the datapoint filename stem:

- `<stem>-base`
- `<stem>-solution`

Derive the instance name this way:

- use datapoint `instance_id` when present
- otherwise use a deterministic fallback based on the datapoint file stem unless the target repository has a stronger local convention

Example:

- `datapoint_1-1.json` -> `datapoint_1-1-base`, `datapoint_1-1-solution`

## Output Contract

This workflow should leave the repository with:

- one `base` branch containing the preflight patch
- one `solution` branch containing the reference result on top of `base`
- `.ee-bench/codegen/metadata.json` on `solution`
- one PR from `solution` to `base`
- the PR added to the `Code Generation` GitHub project: `https://github.com/orgs/dpaia/projects/13`
- the required labels and validator comment

## Worked Example

If the datapoint file is `datapoint_1-1.json` and the JSON contains:

- `id: "1-1"`
- no `instance_id`
- `task_type: "Prototyping"`
- no `base_commit`
- a long `user_prompt`

Then the expected PR wiring is:

- base branch: `datapoint_1-1-base`
- solution branch: `datapoint_1-1-solution`
- instance name fallback: `datapoint_1-1`
- PR title: `[ee-bench] 1-1: Prototyping`
- PR description: exactly the `user_prompt`
- labels: the repo language label, plus `Prototyping`

For the Lyra Unreal repo, the datapoint may not contain a `language` field. In that case, use the repo-appropriate language label rather than leaving it blank. For Lyra, that label is `cpp`.
The same applies to `instance_id`: some datapoints include it and some do not, so the workflow must support both.

## Branch Procedure

Use temporary git worktrees unless there is a good reason not to.

1. Determine the starting point for `base`:
   use datapoint `base_commit` when it exists; otherwise use the repository default branch, which is currently `main`
2. Create `<stem>-base` from that starting point
3. Apply `preflight_patch`
4. Review the result and commit the base branch
5. Create `<stem>-solution` from `<stem>-base`
6. Apply `reference_patch`
7. Review the result and commit the solution branch

The required branch graph is:

- `main` or datapoint `base_commit`
- `<stem>-base`
- `<stem>-solution`

`<stem>-solution` must contain `<stem>-base` as an ancestor. If both branches were created from `main`, or if `base_commit` was ignored when the datapoint provided it, the PR will usually be wrong even if the final files look close.

## Patch Application Rules

Apply the patches in the order the branches were created:

- `preflight_patch` belongs on `base`
- `reference_patch` belongs on `solution`

Treat the solution branch as "base plus the reference result." Do not try to keep `solution` independent from `base`.
Treat `base_commit` the same way: it sets the starting revision for `base`, not an alternate parent for `solution`.

If `reference_patch` overlaps files already changed by `preflight_patch`, the desired end state on `solution` is the reference result while keeping the branch ancestry stacked. That may require a 3-way apply or manual conflict resolution.

Typical example:

- `preflight_patch` adds a failing test scaffold
- `reference_patch` changes the same source file and may also include some of the scaffold context
- correct fix: `solution` still branches from `base`, and the final file contents match the reference outcome

## metadata.json Procedure

Create or update `.ee-bench/codegen/metadata.json` on the `solution` branch only.

Preserve repo-specific scaffold fields already present in the repository. Fill datapoint-specific fields from the JSON:

- `benchmark_type`
  Set to `codegen` if missing.
- `language`
  Use the repo-specific expected value. Do not rely on the datapoint if the datapoint omits it.
- `expected.fail_to_pass`
  Copy from `fail_to_pass_tests`.
- `expected.pass_to_pass`
  Copy from `pass_to_pass_tests`.
- `patch.source_patterns`
  Use the production source file paths touched by the datapoint.
- `patch.test_patterns`
  Use the test file paths touched by the datapoint.

Prefer exact file paths over globs when the datapoint touches a small fixed set of files.

If the repository scaffold or downstream automation expects an instance name:

- use datapoint `instance_id` when present
- otherwise use the deterministic fallback derived earlier
- report which value was used if it was synthesized because the original JSON did not contain `instance_id`

## PR Procedure

Open the PR from `solution` to `base`.

PR title:

- `[ee-bench] <id>: <task_type>`

PR description:

- exactly the `user_prompt` from the datapoint JSON

PR labels:

- one language label
- one `task_type` label

Project assignment:

- add the PR to the `Code Generation` GitHub project: `https://github.com/orgs/dpaia/projects/13`

Validator trigger:

- after the PR is created, add this exact PR comment:
  `@dpaia-validator validate`

## Validation Before Finishing

Confirm all of the following:

- `metadata.json` matches the datapoint fields that matter for evaluation
- the PR diff is only the delta from `base` to `solution`
- the `solution` branch is stacked on top of `base`
- the instance name comes from datapoint `instance_id` when present, or from the documented fallback when it is absent
- the PR is in the `Code Generation` GitHub project before validator invocation
- the PR title, description, labels, and validator comment match convention
- the PR description does not include extra routing metadata unless the user explicitly asked for it

## Repair Mode

When the user asks to fix an existing datapoint PR, inspect the current state and classify the problem before editing anything:

- branch shape problem
- patch application problem
- metadata problem
- PR wiring problem
- GitHub automation or auth problem

Then repair the smallest broken layer first.

Examples:

- If the PR shows add/add conflicts, rebuild `solution` from `base`
- If the validator did not run, check that the PR comment was posted exactly as required
- If the PR body was hand-edited away from `user_prompt`, restore it to the datapoint text

## Notes

- In repos where `.ee-bench/codegen/` scaffolding already exists on `main`, the datapoint PR usually only needs the datapoint-specific `metadata.json` on `solution`
- If PR comments cannot be posted because of auth or repository permissions, report that clearly instead of silently skipping it
