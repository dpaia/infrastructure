# V2 Pipeline Workflows Guide

This document describes every V2 workflow in the EE-Bench datapoint pipeline, how they are triggered by the **issue-validator-bot** GitHub App, their parameters, lifecycle, and interactions with GitHub Projects.

---

## Architecture Overview

The V2 pipeline is an **event-driven system** with two main components:

1. **issue-validator-bot** -- A GitHub App (Express.js service) that listens to webhook events and dispatches workflows. It acts as a thin orchestrator: all actual state mutations happen inside workflows.
2. **V2 workflows** -- GitHub Actions workflows in `dpaia/infrastructure` that perform the heavy lifting (verification, generation, validation, merging, project updates).

### Correlation Mechanism

Every dispatch generates a **UUID v4 run_key** embedded in the workflow's `run-name` as `(key=<uuid>)`. This key:
- Links the workflow run back to the bot's persistence store
- Is stored as `external_id` on PR check runs for crash recovery
- Enables supersession (cancelling old runs when new commits arrive)

### GitHub Projects Used

| Project | Number | Purpose |
|---------|--------|---------|
| Dataset Metadata | 3 | Tracks source PRs through the pipeline (Status, Version, Commit, Data) |
| Codegen Eval | 13 | Eval-type project for codegen datapoints |
| MethodGen Eval | 16 | Eval-type project for methodgen datapoints |

Configuration: `.github/config/eval-projects.json` (infrastructure) and `config/eval-projects.yml` (bot).

### Project Fields

| Field | Type | Values | Used In |
|-------|------|--------|---------|
| Status | single_select | Draft, In progress, Review, Verified, Done, Invalid | Eval projects |
| Verification | single_select | Validating..., Valid, Invalid, Generating..., Generated | Eval projects |
| Version | number | Auto-incremented per generation | Dataset Metadata |
| Commit | text | Source PR head SHA | Dataset Metadata |
| Data | text | Permalink to datapoint JSON on main branch | Dataset Metadata |

---

## Pipeline Lifecycle

The typical happy-path for a datapoint:

```
Source PR created in external repo
         |
         v
User moves PR to "Review" in eval project board
         |  (projects_v2_item webhook -> bot)
         v
[1] verify-source_v2.yml   -- validates the source PR can produce a valid datapoint
         |
         v
Verification field set to "Valid"
         |
         v
User moves PR to "Verified" in eval project board
         |  (projects_v2_item webhook -> bot, gated on Verification == "Valid")
         v
[2] generate-datapoint_v2.yml  -- exports datapoint, creates dataset PR
         |
         v
Dataset PR opened in dpaia/dataset
         |  (pull_request webhook -> bot)
         v
[3] validate-datapoint_v2.yml  -- validates dataset PR, auto-merges on success
         |
         v
Dataset PR merged
         |  (pull_request closed+merged webhook -> bot)
         v
[4] on-datapoint-merged_v2.yml -- updates project fields, closes source PR
```

Additionally:
- **sync-project-fields_v2.yml** resets project state on status reversions or new commits
- **sweep-pipeline-v2.yml** detects and repairs inconsistencies every 6 hours
- **export-dataset-v2.yml** exports the final dataset for evaluation runs

---

## Workflow Reference

### 1. Verify Source PR (`verify-source_v2.yml`)

**Purpose:** Validates that a source PR can produce a correct datapoint by running the export script and validation suite against it. This is a "dry run" -- it generates the datapoint locally and validates it but does not create a dataset PR.

**Workflow name:** `Verify Source PR (v2)`
**Run name:** `[{org}/{repo}] Verify PR #{pr} (key={run_key})`

#### Trigger

| Source | Event | Condition |
|--------|-------|-----------|
| Bot | `projects_v2_item` webhook | PR status changed to **"Review"** in an eval project |
| Bot | `issue_comment` webhook | User comments `@issue-validator validate` on a source PR |
| Manual | `workflow_dispatch` | Via GitHub Actions UI |

When triggered by the bot, the bot:
1. Validates it's a PR (not an issue) in an eval project
2. Checks the PR is in exactly one eval project (multi-project guard)
3. Checks for duplicate transitions (same status + SHA within 24h)
4. Creates a "Datapoint Verification" check run on the source PR
5. Dispatches the workflow via `workflow_dispatch`

#### Parameters

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `organization` | yes | -- | GitHub organization (e.g., `dpaia`) |
| `repository` | yes | -- | Repository name |
| `pr_number` | yes | -- | Source PR number |
| `eval_type` | yes | -- | Evaluation type (`codegen`, `methodgen`, etc.) |
| `run_key` | no | `manual` | UUID correlation key |
| `eval_project_number` | no | `''` | Eval project number for Verification field updates |

#### Lifecycle

1. Sets **Verification** field to `Validating...` in the eval project
2. Runs `setup-ee-import` to install the ee-dataset CLI
3. Runs `run-export-script` to generate a datapoint from the source PR
4. Runs `run-validation` on the generated datapoint
5. Posts a detailed comment on the source PR with results (instance ID, duration, criteria, test results, failed tests)
6. Sets **Verification** field to `Valid` or `Invalid`
7. Uploads validation logs and result JSON as artifacts (7-day / 30-day retention)

#### Outputs

- PR comment with verification results
- Verification field updated on eval project
- Artifacts: `verification-logs-{run_key}`, `verification-result-{run_key}`

#### Bot Completion Handling

When the `workflow_run` completes, the bot:
- Updates the PR check run to passed/failed
- On failure: extracts failure message from workflow run logs

---

### 2. Generate Datapoint (`generate-datapoint_v2.yml`)

**Purpose:** Exports a datapoint from the source PR and creates a new PR in the dataset repository (`dpaia/dataset`). Also registers the source PR in the Dataset Metadata project.

**Workflow name:** `Generate Datapoint (v2)`
**Run name:** `[{org}/{repo}] Generate PR #{pr} (key={run_key})`

#### Trigger

| Source | Event | Condition |
|--------|-------|-----------|
| Bot | `projects_v2_item` webhook | PR status changed to **"Verified"** in an eval project |
| Bot | `issue_comment` webhook | User comments `@issue-validator generate` on a source PR |
| Manual | `workflow_dispatch` | Via GitHub Actions UI |

When triggered by the bot:
1. All standard guards apply (single project, duplicate transition)
2. **Verification gate:** Verification field must be `Valid` -- blocks and reverts if not
3. Creates a "Datapoint Generation" check run on the source PR
4. Reads `dataset_repo` and `export_script` from the bot's eval-projects config

#### Parameters

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `organization` | yes | -- | GitHub organization |
| `repository` | yes | -- | Repository name |
| `pr_number` | yes | -- | Source PR number |
| `eval_type` | yes | -- | Evaluation type |
| `run_key` | no | `manual` | UUID correlation key |
| `dataset_repo` | no | `dpaia/dataset` | Target dataset repository |
| `export_script` | no | `''` | Export script path (relative to `.github/scripts/`, without `.py`) |
| `dataset_project_number` | no | `3` | Dataset Metadata project number |
| `eval_project_number` | no | `''` | Eval project number for Verification field updates |

#### Lifecycle

1. Sets **Verification** field to `Generating...` in the eval project
2. Fetches the source PR head SHA
3. Runs `run-export-script` to generate the datapoint
4. Runs `create-datapoint-pr` to create a PR in the dataset repo (includes structured metadata in PR body)
5. Adds the source PR to the **Dataset Metadata** project
6. Sets Dataset Metadata fields:
   - **Status** = `In Progress`
   - **Version** = previous + 1 (auto-incremented)
   - **Commit** = source PR head SHA
7. Posts a comment on the source PR with instance ID and dataset PR link
8. Sets **Verification** field to `Generated` (on success)

#### Outputs

- New PR in `dpaia/dataset` with the datapoint
- Source PR added to Dataset Metadata project
- Comment on source PR with dataset PR link

#### Dataset PR Metadata Block

The generated dataset PR body contains a structured metadata block:

```
instance_id: <id>
eval_type: <type>
source_repo: <owner/repo>
source_pr: <pr_url>
source_commit: <sha>
source_organization: <org>
source_repository: <repo>
source_pr_number: <number>
```

This metadata is parsed by downstream workflows (`validate-datapoint_v2`, `on-datapoint-merged_v2`).

---

### 3. Validate Datapoint (`validate-datapoint_v2.yml`)

**Purpose:** Validates a dataset PR by checking out the PR's content and running the validation suite. If validation passes, **auto-merges** the dataset PR. If it fails, marks the Dataset Metadata status as `Invalid`.

**Workflow name:** `Validate Datapoint (v2)`
**Run name:** `[dataset] Validate PR #{pr} (key={run_key})`

#### Trigger

| Source | Event | Condition |
|--------|-------|-----------|
| Bot | `pull_request` webhook | Dataset PR `opened` or `synchronize` in a dataset repo |
| Manual | `workflow_dispatch` | Via GitHub Actions UI |

When triggered by the bot:
1. Checks the PR is in a dataset repo (via config)
2. Parses `eval_type` and `instance_id` from the PR body metadata block
3. Passes source PR coordinates for failure status updates
4. Creates a "Datapoint Validation" check run on the dataset PR

#### Parameters

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `organization` | yes | `dpaia` | Dataset repo owner |
| `repository` | yes | `dataset` | Dataset repository name |
| `pr_number` | yes | -- | Dataset PR number to validate |
| `eval_type` | yes | -- | Evaluation type |
| `run_key` | no | `manual` | UUID correlation key |
| `source_organization` | no | `''` | Source PR owner (for failure status updates) |
| `source_repository` | no | `''` | Source PR repo |
| `source_pr_number` | no | `''` | Source PR number |
| `dataset_project_number` | no | `''` | Dataset Metadata project number (for failure status) |

#### Lifecycle

1. Checks out the dataset PR content
2. Detects the instance directory (finds `datapoint.json` in changed files)
3. Runs `run-validation` on the instance directory
4. Posts a comment on the dataset PR with pass/fail result
5. **On success:** Auto-merges the dataset PR (squash merge with branch cleanup)
   - Retries mergeability check up to 3 times
   - Handles merge conflicts gracefully (posts error comment)
   - Defers to sweep if mergeability is unknown
6. **On failure:** Finds the source PR in the Dataset Metadata project and sets Status to `Invalid`
7. Uploads validation logs as artifact

#### Auto-Merge Details

The auto-merge is performed via `gh pr merge --squash --delete-branch`. If the PR has merge conflicts, it posts a comment and exits with failure. If mergeability is undetermined after retries, it silently exits (the sweep pipeline will pick it up).

---

### 4. On Datapoint Merged (`on-datapoint-merged_v2.yml`)

**Purpose:** Post-merge housekeeping after a dataset PR is merged. Updates both the Dataset Metadata and Eval Type projects to "Done" status, sets the Data permalink, and closes the source PR.

**Workflow name:** `On Datapoint Merged (v2)`
**Run name:** `[dataset] Post-merge PR #{pr} (key={run_key})`

#### Trigger

| Source | Event | Condition |
|--------|-------|-----------|
| Bot | `pull_request` webhook | Dataset PR `closed` with `merged=true` in a dataset repo |
| Manual | `workflow_dispatch` | Via GitHub Actions UI |

When triggered by the bot:
- No check run is created (`createCheck: false`) since the PR is already merged

#### Parameters

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `organization` | yes | `dpaia` | Dataset repo owner |
| `repository` | yes | `dataset` | Dataset repository name |
| `pr_number` | yes | -- | Merged dataset PR number |
| `run_key` | no | `manual` | UUID correlation key |
| `dataset_project_number` | no | `''` | Override for Dataset Metadata project number |

#### Lifecycle

1. Loads `eval-projects.json` config
2. Reads merged PR body and parses metadata: `instance_id`, `eval_type`, `source_repo`, `source_pr`, `source_commit`
3. Builds a **Data permalink**: `https://github.com/dpaia/dataset/blob/main/{eval_type}/{source_repo}/{instance_id}.json`
4. **Dataset Metadata project** updates:
   - Sets **Data** field to the permalink
   - Sets **Status** to `Done`
5. **Eval Type project** updates (if configured for this eval_type):
   - Sets **Verification** to `Generated`
   - Sets **Status** to `Done`
6. **Closes the source PR** (not merge -- just close) with comment: "Datapoint pipeline complete. Closing source PR (not merging)."

---

### 5. Sync Project Fields (`sync-project-fields_v2.yml`)

**Purpose:** Resets project board state when a PR's status changes in ways that invalidate previous verification/generation results. Handles three operations: clearing verification, reopening PRs, and resetting state on new commits.

**Workflow name:** `Sync Project Fields (v2)`
**Run name:** `[{org}/{repo}] Sync #{pr} op={operation} (key={run_key})`

#### Trigger

| Source | Event | Condition |
|--------|-------|-----------|
| Bot | `projects_v2_item` webhook | Status moved **away from** "Verified" or "Done" |
| Bot | `pull_request` webhook | Source PR `synchronize` or `reopen` (new commits pushed) |
| Manual | `workflow_dispatch` | Via GitHub Actions UI |

The bot determines the operation:
- **Moving from "Verified" to anything else** -> `clear-verification`
- **Moving from "Done" to anything else** -> `reopen-pr`
- **Source PR receives new commits** -> `reset-on-sync`

#### Parameters

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `organization` | yes | -- | GitHub organization |
| `repository` | yes | -- | Repository name |
| `pr_number` | yes | -- | PR number |
| `operation` | yes | -- | One of: `clear-verification`, `reopen-pr`, `reset-on-sync` |
| `eval_project_number` | yes | -- | Eval project number |
| `run_key` | no | `manual` | UUID correlation key |

#### Operations

**`clear-verification`**
- Clears the **Verification** field in the eval project
- Triggered when PR status moves away from "Verified"

**`reopen-pr`**
- Reopens the source PR if it was closed (the `on-datapoint-merged` workflow closes source PRs)
- Clears the **Verification** field
- Triggered when PR status moves away from "Done" (user wants to re-generate)

**`reset-on-sync`**
- Sets **Status** to `In progress`
- Sets **Verification** to `Validating...`
- Posts comment: "New commit detected -- project status reset to 'In progress'. Previous verification/generation results are stale for the new head SHA."
- Triggered when source PR gets new commits

---

### 6. Sweep Pipeline (`sweep-pipeline-v2.yml`)

**Purpose:** Periodic consistency checker that detects and repairs inconsistencies across eval projects and the Dataset Metadata project. Runs every 6 hours or on-demand.

**Workflow name:** `Sweep Pipeline (v2)`
**Run name:** `Pipeline sweep - detect and repair inconsistencies`

#### Trigger

| Source | Event | Condition |
|--------|-------|-----------|
| Schedule | `cron` | Every 6 hours (`0 */6 * * *`) |
| Manual | `workflow_dispatch` | Optional `dry_run` mode |

#### Parameters

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `dry_run` | no | `false` | If true, detect but do not dispatch repairs |

#### Lifecycle

1. Loads `eval-projects.json` config
2. Queries **all items** from every eval project (paginated GraphQL, handles 100+ items)
3. Queries **all items** from the Dataset Metadata project
4. Runs `sweep_pipeline.py` which:
   - Cross-references eval project items with Dataset Metadata items
   - Detects orphaned items, missing status updates, inconsistent states
   - Generates repair actions (workflow dispatches)
5. If not dry_run, dispatches repair workflows
6. Uploads `sweep-result.json` artifact

#### Use Cases

- Dataset PR was auto-merged but `on-datapoint-merged` didn't fire (webhook lost)
- Bot restarted and lost in-memory persistence (workflow relationships)
- Validation passed but auto-merge was deferred due to mergeability uncertainty
- Status field manually changed without going through the bot

---

### 7. Export Dataset (`export-dataset-v2.yml`)

**Purpose:** Exports the final dataset from the dataset repository for use in evaluation runs. Supports filtering by eval type, GitHub search queries, and output formats.

**Workflow name:** `Export Dataset (v2)`
**Run name:** `Export {eval_type} ({format}) | query: {search_query} | repo: {dataset_repo}`

#### Trigger

| Source | Event | Condition |
|--------|-------|-----------|
| Manual | `workflow_dispatch` | Via GitHub Actions UI |

This workflow is **never triggered by the bot** -- it is a manual operational tool.

#### Parameters

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `eval_type` | yes | `codegen` | Eval type directory (`codegen`, `debugging`, or `all`) |
| `search_query` | no | `''` | GitHub search query for project board filtering (e.g., `label:"Language: C#"`) |
| `format` | yes | `folders` | Output format: `folders` or `jsonl` |
| `output_name` | no | `''` | Artifact name (auto-generated as `dataset-YYYY-MM-DD` if empty) |
| `organization` | no | `dpaia` | GitHub organization |
| `dataset_repo` | no | `dataset` | Dataset repository name |

#### Lifecycle

1. Runs `resolve_instances_v2.py` to build instance list (optionally filtered by search query)
2. Runs `export_datapoints_v2.py` to export instances in the specified format
3. Runs `generate_manifest_v2.py` to create manifest metadata
4. Uploads the exported dataset as a GitHub Actions artifact

---

## Bot Dispatch Mechanics

### Debounce (10s default)

When a source PR receives rapid `synchronize` events (multiple quick commits), the bot debounces them. Only the final SHA is dispatched after a 10-second quiet period. Configurable via `DEBOUNCE_MS`.

### Idempotency

The bot tracks `(workflowType, owner/repo, PR#, headSha)` transitions. Duplicate dispatches for the same combination are blocked for 24 hours. Explicit user commands (`@issue-validator validate`) bypass this with `force: true`.

### Supersession

When a new dispatch arrives for the same PR and workflow type but with a different headSha:
1. Finds the previous workflow run by searching for the old run_key in display titles
2. Cancels the previous workflow run via GitHub Actions API
3. Marks the previous PR check as "Superseded"
4. Removes old persistence entries

### Check Run Lifecycle

For each dispatched workflow, the bot creates a PR check run:
1. **Created** (queued) -- immediately on dispatch, with `external_id = runKey`
2. **In progress** -- when `workflow_run` event fires with `status: in_progress`
3. **Completed** -- when `workflow_run` event fires with `status: completed`

The `external_id` enables crash recovery: if the bot restarts and loses its in-memory store, it can find the check by `external_id` and resume tracking.

### Webhook Events Handled

| Event | Action | Handler |
|-------|--------|---------|
| `projects_v2_item` | `edited` (status change) | Route to verify/generate/sync based on new status |
| `pull_request` | `opened`/`synchronize` (dataset repo) | Dispatch validate-datapoint |
| `pull_request` | `closed` + `merged` (dataset repo) | Dispatch on-datapoint-merged |
| `pull_request` | `synchronize`/`reopen` (source repo) | Dispatch sync (reset-on-sync) |
| `workflow_run` | `in_progress`/`completed` | Update PR check, route completion handling |
| `issue_comment` | `created` (mentions bot) | Parse command (validate/generate), dispatch |

---

## Guards and Safety Mechanisms

| Guard | Where | Behavior |
|-------|-------|----------|
| Multi-project | Bot | PR in >1 eval project blocks all dispatches; posts warning comment |
| Verification gate (Verified) | Bot | Moving to "Verified" requires Verification == "Valid"; reverts + comments if not |
| Verification gate (Done) | Bot | Moving to "Done" requires Verification == "Generated"; reverts + comments if not |
| Duplicate transition | Bot | Same (status, PR, SHA) skipped for 24h |
| Stale completion | Bot | If headSha changed since dispatch, completion is silently dropped |
| Merge conflict | validate-datapoint | Posts error comment, does not auto-merge |
| Missing metadata | on-datapoint-merged | Fails with error if instance_id or eval_type missing from PR body |

---

## Authentication

All workflows use `secrets.PROJECT_TOKEN` -- a token with permissions for:
- Reading/writing GitHub Projects v2
- Creating/merging PRs in the dataset repo
- Posting comments on source PRs
- Closing source PRs
- Running GitHub Actions

The bot authenticates as a GitHub App installation, generating short-lived tokens per repository.

---

## Configuration Files

### Infrastructure: `.github/config/eval-projects.json`

```json
{
  "organization": "dpaia",
  "dataset_metadata_project": "3",
  "eval_projects": {
    "codegen": "13",
    "methodgen": "16"
  }
}
```

### Bot: `config/eval-projects.yml`

```yaml
organization: dpaia
dataset_metadata_project: 3
infra_repo: dpaia/infrastructure
projects:
  - eval_type: codegen
    project_number: 13
    dataset_repo: dpaia/dataset
    export_script: export/codegen/export_unified
  - eval_type: methodgen
    project_number: 16
    dataset_repo: dpaia/dataset
    export_script: export/methodgen/export_unified
```

The bot config includes additional fields (`dataset_repo`, `export_script`) that are passed as workflow inputs during generation dispatch.

---

## Reusable Actions

The V2 workflows use custom composite actions from `.github/actions/`:

| Action | Used By | Purpose |
|--------|---------|---------|
| `setup-ee-import` | verify, generate | Install ee-dataset CLI |
| `run-export-script` | verify, generate | Run the eval-type-specific export script |
| `run-validation` | verify, validate | Run the validation suite on a datapoint |
| `create-datapoint-pr` | generate | Create PR in dataset repo with metadata |
| `find-pr-in-project` | verify, generate, sync, on-merged | Find a PR's item in a GitHub Project |
| `get-pr-node-id` | generate, on-merged | Get GraphQL node ID for a PR |
| `get-project-id` | generate, on-merged | Get GraphQL node ID for a Project |
| `add-issue-to-project` | generate, on-merged | Add/ensure item in a Project |
| `set-project-status` | generate, validate, on-merged, sync | Set Status field |
| `update-project-field` | verify, generate, on-merged, sync | Set any project field |
| `clear-project-field` | sync | Clear a project field value |
| `parse-pr-url` | on-merged | Parse owner/repo/number from PR URL |
| `query-project-items` | sweep | Paginated query of all project items |
