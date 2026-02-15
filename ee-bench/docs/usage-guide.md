# Usage Guide

This guide covers how to install, configure, and run the ee-bench dataset toolkit.

## Installation & Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Git

### Clone and Install

```bash
git clone <repo-url>
cd infrastructure/ee-bench
uv sync
```

### Environment Variables

Set the following tokens as needed for your workflow:

| Variable | Required For | Description |
|----------|-------------|-------------|
| `GITHUB_TOKEN` | GitHub providers, importers | GitHub Personal Access Token with repo scope |
| `HF_TOKEN` | HuggingFace provider | HuggingFace API token (for gated datasets) |

```bash
export GITHUB_TOKEN=ghp_...
export HF_TOKEN=hf_...
```

---

## CLI Commands

### Quick Reference

| Command | Description |
|---------|-------------|
| `ee-dataset generate` | Run the dataset generation pipeline |
| `ee-dataset import run` | Run the import pipeline (creates GitHub PRs) |
| `ee-dataset import dry-run` | Preview import without making changes |
| `ee-dataset import status` | Show import progress summary |
| `ee-dataset import reset` | Remove an item from import state for re-import |
| `ee-dataset run-script <file>` | Execute a Python DSL pipeline script |
| `ee-dataset list` | List available providers and generators |
| `ee-dataset show` | Show resolved config details |
| `ee-dataset check` | Check config file for errors |
| `ee-dataset config` | Show resolved configuration |

### Global Options

| Option | Description |
|--------|-------------|
| `--config, -c <path>` | Path to YAML configuration file |
| `--set, -S KEY=VALUE` | Set template variable (repeatable). Supports JSON values and nested keys. |
| `--verbose, -v` | Increase verbosity (repeatable) |
| `--quiet, -q` | Suppress non-essential output |
| `--version` | Show version and exit |

---

## Running Specifications

### Generate Command

Run a generation pipeline defined in a YAML spec:

```bash
ee-dataset --config <spec>.yaml generate
```

The `generate` command supports both singular (`provider:` / `generator:`) and plural (`providers:` / `generators:`) config formats.

**Generate-specific options:**

| Option | Description |
|--------|-------------|
| `-p, --provider NAME` | Override provider plugin name |
| `-g, --generator NAME` | Override generator plugin name |
| `-s, --selection JSON` | Selection criteria as JSON string or YAML file path |
| `-o, --out PATH` | Override output file path |
| `-f, --format FORMAT` | Override output format (json, jsonl, yaml) |
| `-P key=value` | Provider option (repeatable) |
| `-G key=value` | Generator option (repeatable) |
| `--defer-validation` | Defer compatibility check until after prepare() |

### Import Command

Run an import pipeline that creates GitHub PRs from dataset items:

```bash
# Live import
ee-dataset --config <spec>.yaml import run

# Preview without making changes
ee-dataset --config <spec>.yaml import dry-run

# Check progress
ee-dataset --config <spec>.yaml import status
ee-dataset import status --state-file .state/swe-bench-pro.json

# Reset a specific item for re-import
ee-dataset import reset --instance-id django__django-16255 \
    --state-file .state/swe-bench-pro.json
```

### Run Script Command

Execute a Python DSL pipeline script:

```bash
ee-dataset run-script scripts/my_pipeline.py
ee-dataset run-script scripts/my_pipeline.py -S GITHUB_TOKEN=xxx -S ORG=apache
```

### List Command

Discover available plugins:

```bash
ee-dataset list                # All providers and generators
ee-dataset list -p             # Providers only
ee-dataset list -g             # Generators only
ee-dataset list -v             # With detailed field information
```

---

## Providing Parameters & Overrides

### Environment Variables in YAML

Use `${VAR}` or `${VAR:-default}` syntax in any YAML value:

```yaml
options:
  token: ${GITHUB_TOKEN}           # Required — fails if not set
  hf_token: ${HF_TOKEN:-}          # Optional — empty string default
  org: ${TARGET_ORG:-dpaia}        # Optional — "dpaia" default
  version: "${VERSION:-1}"         # Quoted for YAML string type
```

### Template Variables (-S / --set)

Template variables are substituted via Jinja2 before YAML parsing. Use them for values that change between runs:

```bash
# Simple values
ee-dataset --config spec.yaml -S org=apache -S repo=kafka generate

# JSON values
ee-dataset --config spec.yaml -S 'labels=["bug", "enhancement"]' generate

# Nested keys
ee-dataset --config spec.yaml -S api.timeout=60 generate
```

In the YAML spec, reference them with Jinja2 syntax:

```yaml
selection:
  filters:
    repo: "{{ org }}/{{ repo }}"
```

### CLI Overrides for Generate

The `generate` command accepts direct overrides that take precedence over config values:

```bash
# Override provider and generator
ee-dataset --config spec.yaml generate -p github_pull_requests -g dpaia_jvm

# Override selection
ee-dataset --config spec.yaml generate \
    -s '{"resource": "pull_requests", "filters": {"repo": "apache/kafka", "pr_numbers": [42]}}'

# Override output
ee-dataset --config spec.yaml generate -o custom.jsonl -f json

# Pass provider/generator options
ee-dataset --config spec.yaml generate -P token=xxx -G version=2
```

### Precedence

CLI overrides take highest priority:

```
CLI options (-p, -g, -o, -P, -G)  >  Config file values  >  Defaults
```

For options within the config, nested options are merged:

```
generator.options  <  generator_options (flat)  <  CLI -G options
```

---

## Specification Walkthroughs

### import-swe-bench-pro.yaml — Full Multi-Provider Import

**Purpose:** Import the complete SWE-bench Pro dataset from HuggingFace into a GitHub organization as pull requests, with run scripts attached.

**Providers:**
1. `huggingface` (primary) — loads the SWE-bench Pro dataset from HuggingFace Hub
2. `run_scripts` (enrichment) — fetches run scripts from the SWE-bench Pro open-source repo, matched by `instance_id`

**Generators:**
1. `github_pr_importer` — creates forks, branches, applies patches, creates PRs with metadata, labels, and project assignments
2. `attachment_uploader` — uploads run script and parser files to the PR branches

**Run:**
```bash
export GITHUB_TOKEN=ghp_...
export HF_TOKEN=hf_...
ee-dataset --config specs/import-swe-bench-pro.yaml import run

# Preview first:
ee-dataset --config specs/import-swe-bench-pro.yaml import dry-run
```

---

### export-swe-bench-pro.yaml — Multi-Provider Export

**Purpose:** Export SWE-bench Pro datapoints from GitHub PRs back to JSONL format, extracting embedded metadata and splitting patches.

**Providers:**
1. `github` (primary) — fetches PRs from the `dpaia/*` org with the `swe-bench-pro` label
2. `metadata` (enrichment) — extracts all SWE-bench Pro metadata fields from `<!--METADATA-->` blocks in PR descriptions
3. `patch_splitter` (enrichment) — separates source patches from test patches

**Generators:**
1. `dpaia_swe_pro` — produces records matching the original SWE-bench Pro schema
2. `attachment_downloader` — downloads attachment files from PR branches to local `attachments/` directory

**Run:**
```bash
export GITHUB_TOKEN=ghp_...
ee-dataset --config specs/export-swe-bench-pro.yaml generate
```

---

### import-swe-bench-pro-python.yaml — Filtered Import (Python Only)

**Purpose:** Import only Python tasks from SWE-bench Pro, using the singular config format.

**Key difference from the full import:** Uses `provider:` / `generator:` (singular) with a filter on `repo_language: Python`. Only creates the `github_pr_importer` generator (no attachment upload).

**Run:**
```bash
export GITHUB_TOKEN=ghp_...
export HF_TOKEN=hf_...
ee-dataset --config specs/import-swe-bench-pro-python.yaml import run
```

Language-specific variants also exist for Java, JavaScript, and C++:
- `specs/import-swe-bench-pro-java.yaml`
- `specs/import-swe-bench-pro-javascript.yaml`
- `specs/import-swe-bench-pro-cpp.yaml`

---

### test-single-item-dry-run.yaml — Testing with Dry Run

**Purpose:** Test the import pipeline with a single specific item without making any changes to GitHub.

**Key details:**
- Filters HuggingFace dataset to one `instance_id`
- Sets `inter_operation_delay: 0` for fast execution
- Uses separate state file (`.state/test-dry-run.json`)

**Run:**
```bash
export GITHUB_TOKEN=ghp_...
ee-dataset --config specs/test-single-item-dry-run.yaml import dry-run
```

---

### dpaia-issue.yaml — Issue-Based Generation

**Purpose:** Generate a DPAIA dataset record from a single GitHub issue, with automatic patch splitting.

**Key details:**
- Uses `github_issues` provider with `fetch_commits`, `parse_comments`, and `detect_build_system` enabled
- Uses `patch_splitter` enrichment provider to split source and test diffs
- Requires template variables: `ORGANIZATION`, `REPOSITORY`, `ISSUE_NUMBER`

**Run:**
```bash
ee-dataset --config specs/dpaia-issue.yaml \
    -S ORGANIZATION=apache \
    -S REPOSITORY=kafka \
    -S ISSUE_NUMBER=12345 \
    generate
```

---

### Example Configurations

The `ee-bench/examples/` directory contains additional reference configurations:

| File | Description |
|------|-------------|
| `dpaia_dataset.yaml` | Basic DPAIA dataset generation from GitHub PRs |
| `dpaia_dataset_production.yaml` | Production configuration with full options |
| `dpaia_specific_prs.yaml` | Generate from specific PR numbers |
| `dpaia_jvm_config.yaml` | JVM-specific generation config |
| `dpaia_jvm_multi_provider_config.yaml` | Multi-provider JVM config with patch splitting |
| `full_config.yaml` | Comprehensive config showing all available options |
| `full_features_config.yaml` | Config demonstrating all features |
| `template_config.yaml` | Config using template variables |
| `multi_repo_config.yaml` | Multi-repository generation |
| `search_query_config.yaml` | Using GitHub search queries |
| `test_feature_service.yaml` | Feature service testing config |

---

## Common Workflows

### Import a HuggingFace Dataset as GitHub PRs

1. Set up tokens:
   ```bash
   export GITHUB_TOKEN=ghp_...
   export HF_TOKEN=hf_...
   ```

2. Preview with dry-run:
   ```bash
   ee-dataset --config specs/import-swe-bench-pro.yaml import dry-run
   ```

3. Run the import:
   ```bash
   ee-dataset --config specs/import-swe-bench-pro.yaml import run
   ```

4. Check progress:
   ```bash
   ee-dataset --config specs/import-swe-bench-pro.yaml import status
   ```

### Export GitHub PRs to a JSONL Dataset

1. Ensure PRs exist in the target org with the appropriate label.

2. Run the export:
   ```bash
   ee-dataset --config specs/export-swe-bench-pro.yaml generate
   ```

3. Output is written to the path specified in the spec (e.g., `datasets/swe_bench_pro_export.jsonl`).

### Generate a Dataset from Specific PRs

```bash
ee-dataset --config examples/dpaia_specific_prs.yaml generate
```

Or override the selection on the command line:

```bash
ee-dataset --config examples/dpaia_jvm_config.yaml generate \
    -s '{"resource": "pull_requests", "filters": {"repo": "apache/kafka", "pr_numbers": [14000, 14001]}}'
```

### Generate from a GitHub Issue

```bash
ee-dataset --config specs/dpaia-issue.yaml \
    -S ORGANIZATION=apache \
    -S REPOSITORY=kafka \
    -S ISSUE_NUMBER=12345 \
    generate
```

### Test with Dry Run Before Real Import

Always preview changes before a live import:

```bash
# Dry-run with full spec
ee-dataset --config specs/import-swe-bench-pro.yaml import dry-run

# Or test with a single item
ee-dataset --config specs/test-single-item-dry-run.yaml import dry-run
```

### Check Progress and Reset Items

```bash
# View import progress
ee-dataset --config specs/import-swe-bench-pro.yaml import status

# Or with explicit state file
ee-dataset import status --state-file .state/swe-bench-pro.json

# Reset a failed item for re-import
ee-dataset import reset -i django__django-16255 -s .state/swe-bench-pro.json
```

---

## Troubleshooting

### Plugin Not Found

**Symptom:** `Provider 'xxx' not found` or `Generator 'xxx' not found`

**Solution:** Verify the plugin is installed and registered:

```bash
ee-dataset list
```

If the plugin is missing:
1. Check that the package is listed in `ee-bench/pyproject.toml` dependencies
2. Run `uv sync` to install
3. Verify entry points in the plugin's `pyproject.toml`

### Compatibility Errors

**Symptom:** `Plugin incompatibility: ...` with missing fields

**Solution:** Use `--defer-validation` for providers with dynamic fields (like `huggingface_dataset`):

```bash
ee-dataset --config spec.yaml generate --defer-validation
```

Or add to the config:

```yaml
validation:
  defer: true
```

### Rate Limits

**Symptom:** GitHub API rate limit errors during import

**Solution:** Increase the delay between operations in the generator options:

```yaml
options:
  inter_operation_delay: 2.0    # Seconds between API calls
```

For the GitHub provider, use an authenticated token to get higher rate limits.

### Missing Environment Variables

**Symptom:** Error about undefined variable `${VAR}`

**Solution:** Set the required environment variable:

```bash
export GITHUB_TOKEN=ghp_...
```

Or use a default value in the spec:

```yaml
options:
  token: ${GITHUB_TOKEN:-}       # Empty string if not set
```

### Config Validation

**Symptom:** Unclear config errors

**Solution:** Use the check and show commands to debug:

```bash
# Check config for errors
ee-dataset --config spec.yaml check

# Show resolved config (after template substitution)
ee-dataset --config spec.yaml config
```

### HuggingFace Authentication

**Symptom:** `401 Unauthorized` or `403 Forbidden` when loading gated datasets

**Solution:** Generate a HuggingFace token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) and set it:

```bash
export HF_TOKEN=hf_...
```

Or pass it in the config:

```yaml
options:
  hf_token: ${HF_TOKEN}
```

### Import State Issues

**Symptom:** Items are skipped because they were previously imported

**Solution:** Reset specific items or delete the state file:

```bash
# Reset one item
ee-dataset import reset -i <instance_id> -s .state/swe-bench-pro.json

# Or delete the state file to start fresh (careful — will re-import everything)
rm .state/swe-bench-pro.json
```
