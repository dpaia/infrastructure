EE Benchmark GitHub App

Overview
- This is a minimal GitHub App (Probot-based) that you can install on your GitHub organization.
- It listens for push, pull_request, and issue_comment events on your repositories.
- For each event, it finds referenced issues (e.g., #123, Fixes #123) or detects FAIL_TO_PASS/PASS_TO_PASS in comments, and dispatches a workflow in this infrastructure repository to:
  - Generate dataset data for the issue
  - Verify the instance with the provided test fields
  - Post results back to the issue as a comment

Repository integration
- The workflow that performs the heavy lifting is located in this repository at .github/workflows/process-issue.yml.
- The composite action .github/actions/update-issue-swe-data is responsible for generating dataset data and updating project fields.

Prerequisites
- You must have admin rights to create and install a GitHub App in your organization.
- The App must be installed on:
  1) All source repositories where you want to react to push/PR/comments
  2) This infrastructure repository (so the App can dispatch the workflow here)
- In this infrastructure repository, create a secret named PROJECT_TOKEN (Settings → Secrets and variables → Actions) with sufficient permissions to:
  - Access repository contents
  - Read and write issues
  - Call GraphQL and REST endpoints used by the composite action
  - Trigger and run workflows
  A classic PAT with repo and workflow scopes is acceptable, or use a fine-grained token with equivalent permissions.

Permissions and events
- The App manifest (github-app/app.yml) subscribes to:
  - push
  - pull_request
  - issue_comment
- Minimal permissions required by the App:
  - metadata: read
  - contents: read
  - issues: read
  - pull_requests: read
  - actions: write (needed to dispatch workflows in the infra repository)

Configuration
- Copy github-app/.env.example to .env and fill the values:
  - APP_ID: Your GitHub App ID
  - PRIVATE_KEY: The PEM private key for the App (inline, with \n line breaks)
  - WEBHOOK_SECRET: Webhook secret configured for the App
  - INFRA_REPO: Full name of this infrastructure repo (e.g., my-org/infrastructure)
  - INFRA_REF: Branch or tag used for workflow dispatch (default: main)
  - WORKFLOW_FILE: Path to the workflow in this repo (default: .github/workflows/process-issue.yml)
  - DATASET_REPO: Full name of the dataset repository (e.g., my-org/dataset-repo)
  - GENERATOR: Data generator profile (default: java)
  - AUTO_MERGE: Whether to auto-merge dataset update PRs (default: false)

Local testing
Prerequisites
- Node.js 18+, npm
- smee-client (npm i -g smee-client) or another tunneling tool
- A GitHub App created from github-app/app.yml and installed on your test repositories and this infra repo

Setup
- cd infrastructure/github-app
- cp .env.example .env
- Fill APP_ID, PRIVATE_KEY, WEBHOOK_SECRET
- Set INFRA_REPO (owner/repo of this infrastructure repo)
- Set DATASET_REPO (owner/repo of your dataset repo)
- Optionally set DRY_RUN=true to avoid real workflow dispatches while testing locally

Run the app
- npm install
- npm start
- Verify health: curl http://localhost:3000/health (expect {"status":"ok","dry_run":<true|false>})

Forward webhooks with smee
- smee --url https://smee.io/YOUR_CHANNEL --port 3000
- Configure the GitHub App webhook URL to the smee channel URL
- Ensure the App subscribes to push, pull_request, issue_comment events

Trigger test events
- Push a commit or open/synchronize a PR that references an issue (e.g., "Fixes #123") in a repo where the App is installed
- Or add a comment on an issue containing:
  FAIL_TO_PASS: com.example.MyTest#shouldDoX
  PASS_TO_PASS: com.example.OtherTest#shouldDoY
- Watch the local app logs; in DRY_RUN mode you will see lines like: [DRY_RUN] Would dispatch workflow ...

End-to-end (no DRY_RUN)
- Set DRY_RUN=false in .env and restart the app
- Ensure this infra repo contains .github/workflows/process-issue.yml and has the PROJECT_TOKEN secret
- The app will dispatch the workflow, which generates data, verifies via .github/scripts/verify_java_dataset_instance.sh, and comments results back on the GitHub issue

Notes
- /health endpoint is for local debugging convenience
- If you attempt to run the workflow locally using act, note that verify_java_dataset_instance.sh uses Docker; ensure Docker is available and configured

Deployment
- Deploy to your preferred Node.js hosting (e.g., Render, Railway, Fly.io, Heroku alternative). Ensure environment variables from .env are set in the hosting platform.
- The process should run "npm start" (probot run ./index.js).

How it works
1) On push: the app aggregates commit messages and extracts referenced issues (#123, Fixes #123, etc).
2) On PR events: the app parses PR title and body for referenced issues.
3) On issue comments: if a comment contains FAIL_TO_PASS: or PASS_TO_PASS:, the app triggers the workflow for that issue.
4) For every identified issue, the app calls GitHub Actions workflow_dispatch in this infra repo, passing inputs:
   - organization, repository, issue_id, dataset_repo, generator, auto_merge
5) The process-issue.yml workflow runs, which:
   - Uses the update-issue-swe-data composite action to prepare data
   - If tests are missing, posts a comment asking for FAIL_TO_PASS/PASS_TO_PASS and exits
   - Otherwise, verifies the dataset instance with .github/scripts/verify_java_dataset_instance.sh and posts results as a comment

Notes
- Ensure the App is installed on both the source repos and this infra repo.
- Ensure the infra repo has a PROJECT_TOKEN secret available to workflows.
- The App uses Actions: write permission to dispatch the workflow; actual workflow execution uses PROJECT_TOKEN.

Uninstallation
- You can uninstall the App from your organization’s Installed GitHub Apps settings without affecting historical comments.


Local validation endpoint
- The app exposes an HTTP endpoint to run validation locally without dispatching a GitHub workflow.
- Endpoint: GET /validate?target=org/repo/issues/NUMBER

Prerequisites
- gh CLI installed and authenticated (gh auth login) or provide GH_TOKEN in .env
- Python 3 available (optionally set PYTHON_BIN in .env)
- Docker installed and running (required by verify_java_dataset_instance.sh)

Usage example
- Start the app locally:
  - cd infrastructure/github-app && npm install && npm start
- Ensure .env contains GH_TOKEN (or you have gh auth login)
- Call the endpoint:
  curl 'http://localhost:3000/validate?target=jetbrains-eval-lab/spring-petclinic/issues/79'

What it does
1) Parses the target into organization, repository, and issue number.
2) Fetches linked commits for the issue via GitHub API (gh CLI).
3) Extracts FAIL_TO_PASS and PASS_TO_PASS from issue comments/commits via .github/python/utils/extract_test_fields.py.
4) Generates dataset data locally via .github/python/java.py.
5) If tests are present, runs verification via .github/scripts/verify_java_dataset_instance.sh, which builds and executes tests inside Docker.

Response
- JSON object containing:
  - input: parsed org/repo/issue
  - commits: { commits: [...], base: <sha>, latest: <sha> }
  - test_fields: extracted FAIL_TO_PASS/PASS_TO_PASS/METADATA
  - missing_tests: true if both are empty (verification skipped)
  - data_value: JSON produced by the generator script
  - verification: { status, exit_code, logs } when tests are provided

Notes
- DRY_RUN does not affect this endpoint; it runs everything locally.
- Ensure Docker and gh CLI are properly configured for your machine.
