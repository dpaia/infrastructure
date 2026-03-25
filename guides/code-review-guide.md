# EE-Bench Code Review Guide

How to review datapoints and manage the Code Generation project board.

## Introduction

As a code reviewer, you manage source PRs on the [Code Generation project board](https://github.com/orgs/dpaia/projects/13). Your role is to evaluate whether a contributed PR is suitable for the benchmark, trigger automated verification by setting the correct status, and handle any failures. Most of the pipeline is automated — your main actions are moving PRs between statuses and reviewing verification results.

## Project Board Statuses

| Status | Set By | What It Triggers |
|--------|--------|------------------|
| **Todo** | Manual | Nothing — PR is queued for review |
| **In progress** | Manual or Bot (on new commits) | Nothing — PR is being worked on |
| **Review** | Reviewer | Bot dispatches verification workflow, creates "Datapoint Verification" check, sets Verification="Pending" |
| **Verified** | Reviewer (after verification passes) | Bot dispatches generation workflow, creates "Datapoint Generation" check. **Requires Verification="Passed"** — blocked otherwise |
| **Rejected** | Reviewer | Nothing — PR is rejected with a reason |
| **Done** | Bot (after dataset PR merges) | Nothing — pipeline complete. **Requires Verification="Passed"** — blocked otherwise |

## Verification Field

The project board has a **Verification** single-select field that tracks the automated verification status:

| Value | Set By | Meaning |
|-------|--------|---------|
| **Pending** | Bot (on dispatch or new commits) | Verification is running or hasn't started |
| **Passed** | Bot (on verification success) | Verification passed — PR can move to Verified/Done |
| **Failed** | Bot (on verification failure) | Verification failed — PR cannot move to Verified/Done |

The bot enforces that **Verified** and **Done** statuses require `Verification = "Passed"`. If you move a PR to either status without passing verification, the bot reverts the status and posts a comment explaining why.

## Review Checklist

Before moving a PR to "Review", verify:

- [ ] `.ee-bench/codegen/` directory exists in the repository with required files:
  - `metadata.json` with `instance_id`, `base_commit`, and `expected.fail_to_pass`
  - `environment/Dockerfile`
  - `eval/run.sh`
- [ ] PR body includes a problem statement explaining the issue being solved
- [ ] The code change (gold patch) is a reasonable solution to the described problem

## Reading Verification Results

When you move a PR to "Review", the bot dispatches the verification workflow and creates a "Datapoint Verification" check run on the PR.

### Bot Comment

After verification completes, the bot posts a comment on the PR:

**On success:**
```
✅ Datapoint verification **passed**.

**Instance:** `devlooped__moq-1259`
**Duration:** 45s
**Tests:** Total: 5, Passed: 5, Failed: 0, Skipped: 0
**fail_to_pass:** Expected: 1, Matched: 1
**pass_to_pass:** Expected: 1, Matched: 1
**Criteria:** 6/6 passed
**Details:** [Workflow run](https://github.com/...)
```

**On failure:**
```
❌ Datapoint verification **failed**.

**Instance:** `devlooped__moq-1259`
**Duration:** 120s
**Tests:** Total: 5, Passed: 3, Failed: 2, Skipped: 0
**fail_to_pass:** Expected: 1, Matched: 0
**pass_to_pass:** Expected: 1, Matched: 1
**Criteria:** 4/6 passed, 1 failed, 1 skipped

**Failed criteria:** tests: fail, fail_to_pass: fail

<details><summary>Failed tests (up to 20)</summary>
- com.example.FooTest#testBar: fail
- com.example.FooTest#testBaz: error
</details>

**Details:** [Workflow run](https://github.com/...)
```

### Key Fields to Check

| Field | What to Look For |
|-------|------------------|
| **Tests** | All tests pass (`Failed: 0`) and total count is reasonable |
| **fail_to_pass** | `Matched` equals `Expected` — all expected-to-fail tests failed in baseline and pass after submission |
| **pass_to_pass** | `Matched` equals `Expected` — all expected-to-pass tests still pass after submission |
| **Criteria** | All 6 criteria pass. Criteria may be `skipped` when prerequisites are not met (e.g., empty expected lists) |
| **Failed criteria** | Only appears on failure — indicates which of the 6 criteria didn't pass |
| **Failed tests** | Only appears on failure — lists up to 20 failed test names with status |

### Check Run

In addition to the comment, check the "Datapoint Verification" check run on the PR's **Checks** tab. This shows the overall pass/fail status and links directly to the workflow run.

## Moving to "Verified"

Move a PR to "Verified" **only after** verification passes:

1. Confirm the verification comment shows a pass result
2. Confirm the "Datapoint Verification" check run is green
3. Confirm the **Verification** field shows "Passed"
4. Move the PR to "Verified" on the project board

The bot enforces two gates:
- **Verification field gate**: If the Verification field is not "Passed", the bot reverts the status to its previous value and posts a comment.
- **Check run gate**: If there is no passing "Datapoint Verification" check on the current head SHA, the bot blocks dispatch and posts a comment.

**What happens next:** The bot dispatches the generation workflow, which creates a PR in `dpaia/dataset` containing the exported datapoint. A comment is posted on the source PR linking to the dataset PR.

## Handling Failures

### Verification Failure

If the verification comment shows a failure:

- **Fixable by contributor:** Leave the PR at "Review" or move to "In progress" and comment with what needs to change. The contributor pushes fixes, which resets status to "In progress". Move back to "Review" to re-verify.
- **Unfixable / out of scope:** Move to "Rejected" with a comment explaining the reason.

### Generation Failure

If the dataset PR is not created after moving to "Verified":

1. Check the workflow run logs in the infrastructure repository's Actions tab
2. Look for the "Datapoint Generation" check run on the source PR
3. Common causes: export script errors, dataset repo access issues
4. To retry: toggle the status (move to "In progress", then back to "Verified")

### Validation Failure

If the dataset PR's validation fails (the bot sets status to "Failed" on the Dataset Metadata project):

1. Check the validation comment on the dataset PR in `dpaia/dataset`
2. Common causes: datapoint files don't match expected structure, Docker build fails in clean environment
3. To retry: the contributor fixes the source PR, which resets status to "In progress". Start the review cycle again.

## Post-Verified Automation

After you move a PR to "Verified", no further reviewer action is needed. The pipeline proceeds automatically:

1. **Generation** — Bot creates a dataset PR in `dpaia/dataset` with the exported datapoint
2. **Validation** — Bot dispatches validation on the dataset PR
3. **Auto-merge** — If validation passes, the dataset PR is automatically merged
4. **Finalization** — Both projects (Code Generation and Dataset Metadata) are set to "Done", and the source PR is closed with a comment

If any automated step fails, the bot updates the relevant project status. You can monitor progress through the check runs on the source PR and comments on both the source and dataset PRs.

## New Commits

When new commits are pushed to a source PR that is in **Review**, **Verified**, or **Rejected** status:

- The bot automatically resets all project statuses to **"In progress"**
- The bot resets the **Verification** field to **"Pending"**
- A comment is posted explaining the reset and showing the new head SHA
- Previous verification results are invalidated
- The review process must start over from "Review"

This prevents stale verification results from being used after code changes.
