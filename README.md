# GitHub Actions Workflows

This repository contains several GitHub Actions workflows that automate various tasks related to issue management, data collection, and repository maintenance. Below is a detailed explanation of each workflow.

## Available Workflows

### 1. Update Issue SWE Data

**File:** [.github/workflows/update-issue-swe-data.yml](.github/workflows/update-issue-swe-data.yml)

**Purpose:** Generates software engineering (SWE) benchmark data from issue commits and updates this data for a specific GitHub issue in a project board.

**Trigger:** Manual (workflow_dispatch)

**Inputs:**
- `generator`: Profile to use (default: 'java')
- `organization`: GitHub organization name (default: 'jetbrains-eval-lab')
- `repository`: Repository name
- `issue_id`: Issue number

**Key Jobs:**
1. `get-latest-commit`: Retrieves the latest commit related to the issue
2. `get-issue-id`: Gets the GitHub GraphQL ID for the issue
3. `get-project-data`: Fetches project and field IDs from a GitHub Project
4. `add-to-project`: Adds the issue to the project
5. `extract-test-fields`: Extracts test-related fields from the issue
6. `generate-data`: Generates SWE benchmark data based on the issue and commits
7. `create-gist`: Creates or updates a GitHub Gist with the generated benchmark data
8. `update-data-field`: Updates the "Data" field in the project with the Gist URL
9. `update-status-field`: Updates the "Status" field in the project
10. `update-commit-field`: Updates the "Commit" field with the latest commit hash

**Description:**
This workflow generates software engineering (SWE) benchmark data from issue commits. It extracts data from issues, retrieves commit information, and generate structured benchmark data about them. This data is then stored in GitHub Gists and linked to the issues in a project board.

### 2. Export SWE Dataset

**File:** [.github/workflows/export-dataset.yml](.github/workflows/export-dataset.yml)

**Purpose:** Aggregates and exports generated SWE data from GitHub issues based on search criteria.

**Trigger:** Manual (workflow_dispatch)

**Inputs:**
- `search_query`: GitHub issue search query
- `output_file`: Export file name (default: "dataset.json")
- `update`: Update mode for existing data (options: none, create, force-update)

**Key Jobs:**
1. `find-issues`: Searches for issues matching the query and creates a matrix for parallel processing
2. `process-issues`: Processes each issue in parallel, extracting relevant SWE data
3. `aggregate-results`: Combines all the individual issue data into a single JSON dataset file

**Description:**
This workflow aggregates generated SWE data from issues into a comprehensive dataset. It first searches for issues matching the provided query, then processes each issue in parallel to extract the relevant SWE data, and finally combines all the data into a single JSON file. The resulting dataset can be used for software engineering benchmarks, analysis, reporting, or machine learning purposes. This workflow complements the "Update Issue SWE Data" workflow by collecting and organizing the benchmark data generated for individual issues into a unified dataset.

### 3. Sync Labels to Repositories

**File:** [.github/workflows/sync-labels.yml](.github/workflows/sync-labels.yml)

**Purpose:** Synchronizes GitHub issue labels across multiple repositories.

**Trigger:** Manual (workflow_dispatch)

**Inputs:**
- `profiles`: Comma-separated list of label profiles (e.g., common,spring)
- `topics`: Repository topics to filter by
- `repositories`: Optional specific repositories to target

**Key Jobs:**
1. `search-repositories`: Finds repositories based on topics or uses the provided list
2. `sync-labels-setup`: Prepares the profiles for processing
3. `sync-labels-profile`: Uses a matrix strategy to apply each profile to each repository

**Description:**
This workflow helps maintain consistent issue labels across multiple repositories in the organization. It can target repositories based on topics or a specific list, and apply different label profiles to them. The workflow uses the `github-label-sync` npm package to synchronize labels defined in JSON files (located in `.github/labels/`) to the target repositories.

## Usage Examples

### Update Issue SWE Data

To update SWE data for a specific issue:
1. Go to the "Actions" tab in the repository
2. Select the "Update Issue SWE Data" workflow
3. Click "Run workflow"
4. Fill in the required inputs:
   - Generator profile (e.g., java)
   - Organization name
   - Repository name
   - Issue number
5. Click "Run workflow"

### Export SWE Dataset

To export a dataset of issues:
1. Go to the "Actions" tab in the repository
2. Select the "Export SWE Dataset" workflow
3. Click "Run workflow"
4. Fill in the required inputs:
   - Search query (e.g., `-label:Epic label:Security is:open`)
   - Output file name
   - Update mode
5. Click "Run workflow"
6. Download the generated dataset from the workflow run artifacts

### Sync Labels to Repositories

To synchronize labels across repositories:
1. Go to the "Actions" tab in the repository
2. Select the "Sync Labels to Repositories" workflow
3. Click "Run workflow"
4. Fill in the required inputs:
   - Label profiles to apply
   - Repository topics to filter by (or specific repositories)
5. Click "Run workflow"