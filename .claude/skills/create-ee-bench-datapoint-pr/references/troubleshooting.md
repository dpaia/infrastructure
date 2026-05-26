# Troubleshooting

## PR Shows Merge Conflicts

Likely cause:

- `base` and `solution` were both created from `main`

Typical symptom:

- add/add conflict on files created by both patches

Fix:

1. Recreate `base` from `main`
2. Apply `preflight_patch` to `base`
3. Recreate `solution` from `base`
4. Apply `reference_patch` to `solution`
5. Force-push `solution`

## Automation Cannot Determine Eval Type

Preferred fix in this workflow:

- make sure the PR comment `@dpaia-validator validate` was posted after the PR was opened

Current team convention:

- include `[ee-bench]` in the PR title

Do not assume the title alone is sufficient routing metadata.

## Verification Workflow Fails Before Validation Starts

If the workflow fails during `Checkout infrastructure` with a `403`, and the log mentions that the account is suspended, the problem is workflow credentials or repository access, not the datapoint content.

Typical follow-on errors such as artifact uploads missing `path` are secondary failures caused by the earlier checkout error.

## metadata.json Looks Wrong

Check these first:

- `expected.fail_to_pass` matches `fail_to_pass_tests`
- `expected.pass_to_pass` matches `pass_to_pass_tests`
- `patch.source_patterns` contains only source files
- `patch.test_patterns` contains only test files
- repo-specific scaffold fields were preserved instead of replaced wholesale

## Validator Comment Fails

Likely cause:

- the current GitHub token cannot post PR comments in the target repository

Fix:

- retry with a token or auth context that can comment on the PR

## Tests Cannot Be Run Locally

For Unreal datapoints, this is expected when:

- no local `UnrealEditor` binary is available
- no usable Unreal container image is available

In that case, report that test execution is blocked by missing runtime prerequisites instead of guessing.
