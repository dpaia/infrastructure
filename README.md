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

**Inputs:** `organization`, `repository`, `pr_number`, `eval_type`, `run_key`

**What it does:**
1. Runs the export script to generate a datapoint from the source PR
2. Runs `validate.sh` against the generated datapoint
3. Posts a comment on the source PR with pass/fail result, test summary, and failed test details
4. Uploads validation logs and result JSON as artifacts

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

**Inputs:** `organization`, `repository`, `pr_number`, `eval_type`, `run_key`

**What it does:**
1. Checks out the dataset PR branch
2. Detects the instance directory from changed files
3. Runs `validate.sh` against the datapoint
4. Posts a comment on the dataset PR with pass/fail result
5. Uploads validation logs as artifacts

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

**Purpose:** Detects and repairs inconsistencies in the pipeline state.

**Trigger:**
- **Scheduled:** Every 6 hours (`0 */6 * * *`)
- **Manual:** `workflow_dispatch`

**What it does:**
1. Queries all eval type projects and the Dataset Metadata project
2. Finds source PRs in "Review" without a verification check → dispatches `verify-source_v2.yml`
3. Finds source PRs in "Verified" without a dataset PR → dispatches `generate-datapoint_v2.yml`
4. Finds merged dataset PRs not marked "Done" → dispatches `on-datapoint-merged_v2.yml`

---

## Reusable Composite Actions

| Action | Purpose |
|--------|---------|
| `parse-pr-url` | Extracts owner, repo, and number from a GitHub PR URL |
| `get-pr-node-id` | Gets the GraphQL node ID for a pull request |
| `get-issue-node-id` | Gets the GraphQL node ID for an issue |
| `get-project-id` | Fetches a GitHub Project V2 ID by organization and number |
| `add-issue-to-project` | Adds an issue/PR to a GitHub Project V2 |
| `set-project-status` | Sets the Status field on a project item |
| `update-project-field` | Updates any field on a project item (text, number, etc.) |
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
| **issue-validator-bot** | [`dpaia/issue-validator-bot`](https://github.com/dpaia/issue-validator-bot) | GitHub App that listens to webhooks and dispatches v2 workflows |
| **ee-bench-import** | [`dpaia/ee-bench-import`](https://github.com/dpaia/ee-bench-import) | Export scripts, validation script, ee-dataset CLI source |
| **Dataset repository** | [`dpaia/dataset`](https://github.com/dpaia/dataset) | Stores generated datapoints |
