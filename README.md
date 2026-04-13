# EE-Bench Infrastructure

GitHub Actions workflows, composite actions, and scripts that power the EE-Bench datapoint pipeline. All automation lives in this repository (`dpaia/infrastructure`) and operates on source PRs in `dpaia/*` repos and the dataset repository (`dpaia/dataset`).

## Architecture Overview

The pipeline turns source PRs into validated datapoints through five stages, tracked via two GitHub Projects:

- **Eval Type projects** (one per eval type, e.g. "Code Generation") — track source PRs through Review → Verified → Done
- **Dataset Metadata project** — tracks generated datapoint PRs through In Progress → Done

```
Source PR in dpaia/* repo
  │  Team marks status → Review
  ▼
┌─────────────────────────────────────────┐
│  Stage 1: Verify Source                  │
│  verify-source_v2.yml                    │
│  Generate datapoint + run validation     │
│  Post check result on source PR          │
└──────────────┬──────────────────────────┘
               │  Review team sets status → Verified
               ▼
┌─────────────────────────────────────────┐
│  Stage 2: Generate Datapoint             │
│  generate-datapoint_v2.yml               │
│  Create PR in dpaia/dataset              │
│  Track in Dataset Metadata project       │
└──────────────┬──────────────────────────┘
               │  Dataset PR created
               ▼
┌─────────────────────────────────────────┐
│  Stage 3: Validate Datapoint             │
│  validate-datapoint_v2.yml               │
│  Run validation on dataset PR contents   │
│  Post result comment on dataset PR       │
└──────────────┬──────────────────────────┘
               │  Dataset PR merged
               ▼
┌─────────────────────────────────────────┐
│  Stage 4: Post-Merge                     │
│  on-datapoint-merged_v2.yml              │
│  Set both projects to Done               │
│  Close source PR                         │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  Export (on demand)                      │
│  export-dataset-v2.yml                   │
│  Bulk export datapoints as folders/JSONL │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  Sweep (scheduled)                       │
│  sweep-pipeline-v2.yml                   │
│  Detect and repair pipeline gaps         │
└─────────────────────────────────────────┘
```

## Documentation

| Guide | Audience | Description |
|-------|----------|-------------|
| [Contribution Guide](guides/contribution-guide.md) | Developers | How to create source PRs with `.ee-bench/` configuration |
| [Code Review Guide](guides/code-review-guide.md) | Review team | How to validate datapoints and manage the project board |
| [Evaluation Guide](guides/evaluation-guide.md) | Evaluation team | How to export datasets and run validation |

## Dataset Repository Layout

Datapoints in `dpaia/dataset` are organized as `<eval_type>/<repo>/<instance_id>`:

```
dpaia/dataset/
├── codegen/
│   ├── spectre.console/
│   │   ├── spectreconsole__spectre.console-1708.json   # flat JSON (all content inlined)
│   │   └── spectreconsole__spectre.console-1708/       # structured folder
│   │       ├── datapoint.json
│   │       ├── environment/
│   │       ├── eval/
│   │       └── verify/
│   └── spring-boot-microshop/
│       └── ...
└── debugging/
    └── ...
```

## V2 Workflows

### Verify Source PR

**File:** `.github/workflows/verify-source_v2.yml`

**Purpose:** Generates a datapoint from a source PR and runs validation to verify the PR is suitable for the benchmark.

**Trigger:**
- **Automatic:** Bot dispatches when source PR status changes to "Review" in an eval type project
- **Manual:** `workflow_dispatch`

**Inputs:** `organization`, `repository`, `pr_number`, `eval_type`, `run_key`, `eval_project_number`

**What it does:**
1. If `eval_project_number` is set: finds the PR in the eval project and sets Verification="Validating..."
2. Runs the export script to generate a datapoint from the source PR
3. Runs `validate.sh` against the generated datapoint
4. If `eval_project_number` is set: sets Verification="Valid" or "Invalid" based on the result
5. Posts a comment on the source PR with pass/fail result, test summary, and failed test details
6. Uploads validation logs and result JSON as artifacts

---

### Generate Datapoint

**File:** `.github/workflows/generate-datapoint_v2.yml`

**Purpose:** Generates a datapoint from a verified source PR and creates a PR in the dataset repository.

**Trigger:**
- **Automatic:** Bot dispatches when source PR status changes to "Verified" in an eval type project
- **Manual:** `workflow_dispatch`

**Inputs:** `organization`, `repository`, `pr_number`, `eval_type`, `run_key`, `dataset_repo`, `export_script`, `dataset_project_number`

**What it does:**
1. Runs the export script to generate a datapoint (flat JSON + structured folder)
2. Creates/updates a PR in `dpaia/dataset` with the datapoint files under `<eval_type>/<repo>/<instance_id>`
3. Adds the source PR to the Dataset Metadata project with status "In Progress"
4. Increments the Version field and records the source commit SHA
5. Posts a comment on the source PR linking to the dataset PR

---

### Validate Datapoint

**File:** `.github/workflows/validate-datapoint_v2.yml`

**Purpose:** Validates a datapoint PR in the dataset repository.

**Trigger:**
- **Automatic:** Bot dispatches when a PR is opened/updated in `dpaia/dataset`
- **Manual:** `workflow_dispatch`

**Inputs:** `organization`, `repository`, `pr_number`, `eval_type`, `run_key`, `source_organization`, `source_repository`, `source_pr_number`, `dataset_project_number`

**What it does:**
1. Checks out the dataset PR branch
2. Detects the instance directory from changed files
3. Runs `validate.sh` against the datapoint
4. On success: auto-merges the dataset PR (squash merge with mergeability retry loop)
5. On failure + `dataset_project_number` set: finds the source PR in the Dataset Metadata project and sets Status="Invalid"
6. Posts a comment on the dataset PR with pass/fail result
7. Uploads validation logs as artifacts

---

### On Datapoint Merged

**File:** `.github/workflows/on-datapoint-merged_v2.yml`

**Purpose:** Finalizes the pipeline after a dataset PR is merged — updates project statuses and closes the source PR.

**Trigger:**
- **Automatic:** Bot dispatches when a PR is merged in `dpaia/dataset`
- **Manual:** `workflow_dispatch`

**Inputs:** `organization`, `repository`, `pr_number`, `run_key`, `eval_project_map`, `dataset_project_number`

**What it does:**
1. Parses metadata from the merged dataset PR body (instance_id, eval_type, source_pr, source_repo)
2. Sets the Dataset Metadata project status to "Done" and updates the Data field with a permalink
3. Sets the eval type project status to "Done" for the source PR
4. Closes the source PR with a comment (not merged)

---

### Export Dataset

**File:** `.github/workflows/export-dataset-v2.yml`

**Purpose:** Bulk exports datapoints from the dataset repository as a downloadable artifact.

**Trigger:** Manual (`workflow_dispatch`)

**Inputs:** `eval_type`, `search_query`, `format` (folders or jsonl), `output_name`, `organization`, `dataset_repo`

**What it does:**
1. Checks out the dataset repository
2. Resolves instance IDs — either from a GitHub PR search query or by scanning the filesystem
3. Exports each instance as folder or JSONL format
4. Generates a manifest with metadata (eval type, count, commit SHA, timestamps)
5. Uploads the export as a GitHub Actions artifact (retained 30 days)

---

### Sweep Pipeline

**File:** `.github/workflows/sweep-pipeline-v2.yml`
**Script:** `.github/python/sweep_pipeline.py`

**Purpose:** Detects and repairs inconsistencies in the pipeline state. Acts as a safety net for dropped events, bot restarts, failed workflows, and manual board edits that leave the pipeline in an inconsistent state.

**Trigger:**
- **Scheduled:** Every 6 hours (`0 */6 * * *`)
- **On bot startup:** The issue-validator-bot dispatches a sweep on every deploy/restart to catch state lost from in-memory persistence
- **Manual:** `workflow_dispatch`

**How it works:**
1. Queries all eval type projects and the Dataset Metadata project via GraphQL (with pagination)
2. Runs each consistency check against the queried items
3. For each inconsistency found, either repairs it directly (API call) or dispatches the appropriate workflow
4. Produces a JSON summary artifact with all issues found and repairs made

**Consistency checks:**

| Check | Inconsistent State | How Detected | Repair |
|-------|--------------------|--------------|--------|
| **Missing verification** | Source PR in "Review" with no "Datapoint Verification" check run on HEAD | Query check runs for the PR's head SHA | Dispatch `verify-source_v2.yml` |
| **Closed PR in active status** | Source PR is closed but project status is "In Progress", "Review", or "Verified" | Compare PR state from GraphQL against project Status field | Reopen the PR via REST API (skip if merged — can't reopen) |
| **Verified without Verification=Valid** | Source PR in "Verified" but Verification field is not "Valid" | Field value mismatch | Report only — needs manual investigation (possible guard bypass) |
| **Verified with closed source PR** | Source PR in "Verified" but PR is closed/merged | PR state check | Reopen if closed (not merged); report if merged |
| **Verified without dataset PR** | Source PR in "Verified" but no dataset PR exists in the Dataset Metadata project | Cross-reference eval items against dataset items by source PR URL | Dispatch `generate-datapoint_v2.yml` |
| **Verified with all dataset PRs closed** | Source PR in "Verified" but all linked dataset PRs are closed (not merged) | Dataset PR state check — indicates failed generation | Dispatch `generate-datapoint_v2.yml` (re-generation) |
| **Merged dataset PR not Done** | Dataset PR is merged but project status is not "Done" | Compare PR state against Status field | Dispatch `on-datapoint-merged_v2.yml` |
| **Stale check runs** | Pipeline check run ("Datapoint Verification", "Datapoint Generation", or "Datapoint Validation") stuck `in_progress` for over 1 hour | Query check runs on active PRs, compare `started_at` to current time | PATCH check to `completed` with conclusion `timed_out` |

**API considerations:**
- Status filtering limits check-runs queries to PRs in active statuses only (~10-30 API calls instead of scanning all items)
- SHA deduplication avoids redundant queries when multiple project items reference the same commit
- Rate-limited API helper (`gh_rate_limited`) adds 100ms inter-call delay and retries on rate limit responses, reading the actual wait period from `Retry-After` or `X-RateLimit-Reset` headers
- Paginated check-runs queries via `gh api --paginate --slurp`

**Inputs:** `dry_run` (detect only, no repairs), `eval_projects` (JSON map of eval_type to project_number), `dataset_project_number`, `organization`

---

### Sync Project Fields

**File:** `.github/workflows/sync-project-fields_v2.yml`

**Purpose:** Performs project field mutations (clear verification, reopen PR, reset status) dispatched by the bot when project status changes or new commits arrive.

**Trigger:**
- **Automatic:** Bot dispatches on status regression from Verified/Done or on source PR synchronize
- **Manual:** `workflow_dispatch`

**Inputs:** `organization`, `repository`, `pr_number`, `operation`, `eval_project_number`, `run_key`

**Operations:**
- `clear-verification`: Clears the Verification field on the eval project item
- `reopen-pr`: Reopens the PR if closed (not merged) and clears Verification
- `reset-on-sync`: Sets Status="In progress", Verification="Validating...", and posts an informational comment on the PR

---

## Reusable Composite Actions

| Action | Purpose |
|--------|---------|
| `parse-pr-url` | Extracts owner, repo, and number from a GitHub PR URL |
| `get-pr-node-id` | Gets the GraphQL node ID for a pull request |
| `get-issue-node-id` | Gets the GraphQL node ID for an issue |
| `get-project-id` | Fetches a GitHub Project V2 ID by organization and number |
| `add-issue-to-project` | Adds an issue/PR to a GitHub Project V2 |
| `find-pr-in-project` | Resolves PR node ID, project ID, and adds PR to project (combines get-pr-node-id + get-project-id + add-issue-to-project) |
| `set-project-status` | Sets the Status field on a project item |
| `update-project-field` | Updates any field on a project item (text, number, single-select) |
| `clear-project-field` | Clears a field value on a project item |
| `get-project-field-value` | Reads a field value from a project item |
| `query-project-items` | Queries all items in a project with their field values |
| `run-export-script` | Resolves and runs an export script to generate a datapoint |
| `run-validation` | Runs `validate.sh` and extracts structured results (status, test summary, failures) |
| `create-datapoint-pr` | Creates/updates a PR in the dataset repo with datapoint files and metadata |
| `setup-ee-import` | Installs the ee-dataset CLI from the bundled wheel |

## Legacy Workflows (v1)

The following workflows predate the v2 pipeline and are kept for backward compatibility during migration. They should not be used for new work.

| Workflow | File | Purpose |
|----------|------|---------|
| Update Issue Dataset Data | `update-issue-data.yml` | Generate a single datapoint from an issue |
| Generate Dataset Data | `generate-dataset-data.yml` | Batch generate datapoints from issues matching a search query |
| Export Dataset | `export-dataset.yml` | Export dataset to `dpaia/ee-dataset` repository |
| Validate Issue | `validate-issue.yml` | Validate a single issue's datapoint |
| Validate External Repo Issue | `validate-external-repo-issue.yml` | Validate an issue from an external repository |
| Validate Dataset | `validate-dataset.yml` | Validate dataset items |
| Process Issue | `process-issue.yml` | Process a single issue through the pipeline |

## Utility Workflows

| Workflow | File | Trigger | Purpose |
|----------|------|---------|---------|
| Sync Labels | `sync-labels.yml` | Manual | Synchronize issue labels across repositories |
| Add Issues to Project | `add-issues-to-project.yml` | Manual / Daily | Add matching issues to a project board |
| Share Custom Workflows | `share-custom-workflows.yml` | Manual | Distribute workflow files to other repositories via PRs |

## Shared Workflows

These reusable workflows are called by workflows in other `dpaia/*` repositories:

| Workflow | File | Purpose |
|----------|------|---------|
| Collect and Process Tests | `shared-collect-process-tests.yml` | Extract FAIL_TO_PASS / PASS_TO_PASS test lists from issues |
| Run Tests Maven | `shared-run-tests-maven.yml` | Run Maven tests and report results on issues |
| Maven (shared template) | `shared/.github/workflows/maven.yml` | Standalone Maven test workflow distributed to repositories |

## Related Components

| Component | Location | Purpose |
|-----------|----------|---------|
| **issue-validator-bot** | [`dpaia/issue-validator-bot`](https://github.com/dpaia/issue-validator-bot) | Thin orchestrator: receives webhooks, validates/guards, dispatches v2 workflows, manages check runs |
| **ee-bench-import** | [`dpaia/ee-bench-import`](https://github.com/dpaia/ee-bench-import) | Export scripts, validation script, ee-dataset CLI source |
| **Dataset repository** | [`dpaia/dataset`](https://github.com/dpaia/dataset) | Stores generated datapoints |
