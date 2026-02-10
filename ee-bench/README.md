# ee-bench

A pluggable dataset generator for creating evaluation benchmarks from GitHub pull requests and issues.

## Overview

ee-bench is a CLI tool that generates datasets in formats compatible with SWE-bench and similar evaluation frameworks. It uses a plugin architecture where:

- **Providers** fetch data from external sources (GitHub PRs, issues, etc.)
- **Generators** transform that data into specific output formats (DPAIA, SWE-bench, etc.)

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd ee-bench

# Install with uv (recommended)
uv sync

# Or install with pip
pip install -e .
```

## Quick Start

```bash
# Set your GitHub token
export GITHUB_TOKEN=your_github_token

# Option 1: Use a complete config file (recommended)
ee-dataset --config config.yaml generate

# Option 2: Config file with template variables
ee-dataset --config config.yaml -S org=apache -S project=kafka generate

# Option 3: All options via CLI
ee-dataset generate \
    -p github_pull_requests \
    -g dpaia_jvm \
    -s '{"resource": "pull_requests", "filters": {"repo": "owner/repo", "pr_numbers": [123]}}' \
    --out dataset.jsonl

# Option 4: Config file with CLI overrides
ee-dataset --config config.yaml generate -o custom_output.jsonl
```

## Commands

### List available plugins

```bash
ee-dataset list                    # List all providers and generators
ee-dataset list --providers        # List only providers
ee-dataset list --generators       # List only generators
```

### Show plugin details

```bash
ee-dataset show provider github_pull_requests
ee-dataset show generator dpaia_jvm
```

### Check compatibility

```bash
ee-dataset check -p github_pull_requests -g dpaia_jvm
```

### Generate dataset

```bash
# Using a complete config file
ee-dataset --config config.yaml generate

# Using CLI options
ee-dataset generate \
    --provider github_pull_requests \
    --generator dpaia_jvm \
    --selection selection.yaml \
    --out output.jsonl \
    --format jsonl
```

**Options** (can be set via CLI or config file, CLI overrides config):
- `-p, --provider` - Provider plugin name
- `-g, --generator` - Generator plugin name
- `-s, --selection` - Selection criteria as JSON string or YAML file path
- `-o, --out` - Output file path (default: out.jsonl)
- `-f, --format` - Output format: json, jsonl, yaml (default: jsonl)
- `-P, --provider-option` - Provider option as key=value (can be repeated)
- `-G, --generator-option` - Generator option as key=value (can be repeated)

### Show output schema

```bash
ee-dataset schema -g dpaia_jvm
```

### Configuration commands

```bash
ee-dataset config init             # Generate sample config file
ee-dataset config show             # Show current config
ee-dataset config validate config.yaml  # Validate a config file
```

### Template variables (`--set` / `-S`)

Pass template variables to config files using the `--set` or `-S` option:

```bash
# Simple values
ee-dataset -c config.yaml -S org=apache -S project=kafka generate

# JSON arrays
ee-dataset -c config.yaml -S 'labels=["bug", "verified"]' generate

# Nested keys
ee-dataset -c config.yaml -S api.timeout=60 generate

# Multiple options
ee-dataset -c config.yaml \
  -S org=apache \
  -S 'repos=["kafka", "flink"]' \
  -S limit=50 \
  generate
```

## Configuration File Specification

Configuration files use YAML format with support for Jinja2 templates and environment variable substitution.

### Basic Structure

```yaml
# config.yaml - Complete configuration example
provider: github_pull_requests
generator: dpaia_jvm

provider_options:
  api:
    timeout: 60
    max_retries: 5

generator_options:
  include_metadata: true

selection:
  resource: pull_requests
  filters:
    repo: apache/kafka
    state: closed
  limit: 100

output:
  format: jsonl
  path: datasets/output.jsonl
```

### Jinja2 Templates

Config files support Jinja2 templating with variables passed via `--set` / `-S`:

```yaml
# template_config.yaml
provider: github_pull_requests
generator: dpaia_jvm

selection:
  resource: pull_requests
  filters:
    repo: "{{ org }}/{{ project }}"
    state: {{ state | default('closed') }}
  limit: {{ limit | default(100) }}

output:
  path: datasets/{{ org }}_{{ project }}_dataset.jsonl
```

Usage:
```bash
ee-dataset -c template_config.yaml -S org=apache -S project=kafka generate
```

#### Template Features

| Feature | Syntax | Example |
|---------|--------|---------|
| Variable | `{{ var }}` | `{{ org }}/{{ project }}` |
| Default value | `{{ var \| default(value) }}` | `{{ limit \| default(100) }}` |
| Conditional | `{% if var %}...{% endif %}` | See below |
| Loop | `{% for item in list %}...{% endfor %}` | See below |

**Conditional blocks:**
```yaml
selection:
  filters:
{% if labels is defined and labels %}
    labels:
{% for label in labels %}
      - {{ label }}
{% endfor %}
{% endif %}
```

**Usage with JSON arrays:**
```bash
ee-dataset -c config.yaml -S 'labels=["bug", "verified"]' generate
```

### Environment Variables

Environment variable substitution uses `${VAR}` syntax:

```yaml
provider_options:
  token: ${GITHUB_TOKEN}           # Required - fails if not set
  org: ${GITHUB_ORG:-apache}       # With default value
```

### Selection Filters

The `selection.filters` section specifies what data to fetch.

#### Single Repository

```yaml
selection:
  filters:
    repo: apache/kafka
    state: closed
```

#### Multiple Repositories

```yaml
selection:
  filters:
    repos:
      - apache/kafka
      - apache/flink
      - apache/spark
    state: closed
```

#### Wildcard Patterns

Use glob-style patterns to match multiple repositories:

```yaml
selection:
  filters:
    # All repos in an organization
    repo: "apache/*"

    # Pattern matching
    repo: "apache/kafka-*"    # Matches kafka-clients, kafka-streams, etc.

    # Multiple patterns
    repos:
      - "apache/kafka*"
      - "apache/flink"
```

**Supported wildcards:**
- `*` - Matches any characters (e.g., `kafka-*` matches `kafka-clients`)
- `?` - Matches single character (e.g., `v?` matches `v1`, `v2`)

#### GitHub Search Query

Use GitHub's search syntax for complex queries:

```yaml
selection:
  filters:
    # Search query - mutually exclusive with repo/repos
    query: "is:pr is:merged label:bug repo:apache/kafka"
  limit: 50
```

**Note:** The `query` filter cannot be combined with `repo` or `repos`. Include repository filters in the search query string instead.

**Search query examples:**
```yaml
# Merged PRs with bug label
query: "is:pr is:merged label:bug repo:apache/kafka"

# PRs across an organization
query: "is:pr is:merged org:apache language:java"

# PRs by author
query: "is:pr author:username repo:owner/repo"

# PRs in date range
query: "is:pr merged:2024-01-01..2024-06-30 repo:apache/kafka"
```

#### Specific Items

```yaml
selection:
  filters:
    repo: apache/kafka
    pr_numbers:        # For pull requests
      - 14521
      - 14498
    # Or for issues:
    # issue_numbers:
    #   - 1234
```

#### Label Filtering

```yaml
selection:
  filters:
    repo: apache/kafka
    labels:
      - bug
      - verified
    state: closed
```

### Complete Examples

#### Static Configuration

```yaml
provider: github_pull_requests
generator: dpaia_jvm

selection:
  resource: pull_requests
  filters:
    repo: apache/kafka
    state: closed
    labels:
      - bug
  limit: 50

output:
  format: jsonl
  path: datasets/kafka_bugs.jsonl
```

#### Template Configuration

```yaml
provider: github_pull_requests
generator: dpaia_jvm

selection:
  resource: pull_requests
  filters:
    repos:
{% for repo in repos | default(['kafka']) %}
      - "{{ org }}/{{ repo }}"
{% endfor %}
    state: {{ state | default('closed') }}
{% if labels is defined %}
    labels:
{% for label in labels %}
      - {{ label }}
{% endfor %}
{% endif %}
  limit: {{ limit | default(100) }}

output:
  format: jsonl
  path: datasets/{{ org }}_dataset.jsonl
```

Usage:
```bash
ee-dataset -c config.yaml \
  -S org=apache \
  -S 'repos=["kafka", "flink"]' \
  -S 'labels=["bug"]' \
  -S limit=50 \
  generate
```

#### Search Query Configuration

```yaml
provider: github_pull_requests
generator: dpaia_jvm

selection:
  resource: pull_requests
  filters:
    query: "is:pr is:merged repo:apache/kafka"
  limit: 100

output:
  format: jsonl
  path: datasets/search_results.jsonl
```

## Available Plugins

### Providers

#### github_pull_requests

Fetches data from GitHub pull requests.

**Provided fields:**
- `description` - PR body text
- `title` - PR title
- `labels` - List of label names
- `number` - PR number
- `base_commit` - Base branch SHA
- `head_commit` - Head branch SHA
- `commits` - List of commit SHAs
- `patch` - Combined diff
- `FAIL_TO_PASS` - Tests that should fail then pass (parsed from PR body)
- `PASS_TO_PASS` - Tests that should always pass (parsed from PR body)
- `repo_url` - Repository clone URL
- `repo_tree` - List of files at base commit

**Selection filters:**

| Filter | Type | Description |
|--------|------|-------------|
| `repo` | string | Single repository (`owner/repo`) |
| `repos` | list | Multiple repositories |
| `query` | string | GitHub search query (mutually exclusive with repo/repos) |
| `pr_numbers` | list | Specific PR numbers to fetch |
| `state` | string | PR state: `open`, `closed`, `all` |
| `labels` | list | Filter by label names |

**Pattern support:** Both `repo` and `repos` support wildcard patterns:
- `apache/*` - All repos in organization
- `apache/kafka-*` - Repos matching pattern

#### github_issues

Fetches data from GitHub issues.

**Provided fields:**
- `description` - Issue body text
- `title` - Issue title
- `labels` - List of label names
- `number` - Issue number
- `repo_url` - Repository clone URL
- `repo_tree` - List of files in repository

**Selection filters:**

| Filter | Type | Description |
|--------|------|-------------|
| `repo` | string | Single repository (`owner/repo`) |
| `repos` | list | Multiple repositories |
| `issue_numbers` | list | Specific issue numbers to fetch |
| `state` | string | Issue state: `open`, `closed`, `all` |
| `labels` | list | Filter by label names |

**Pattern support:** Same as github_pull_requests.

### Generators

#### dpaia_jvm

Generates DPAIA-format records for JVM projects, compatible with SWE-bench evaluation.

**Output schema:**
```json
{
  "instance_id": "owner__repo__123",
  "repo": "https://github.com/owner/repo.git",
  "base_commit": "abc123...",
  "patch": "diff --git ...",
  "problem_statement": "Title\n\nDescription",
  "hints_text": "",
  "FAIL_TO_PASS": "[\"test.Class.method\"]",
  "PASS_TO_PASS": "[]",
  "created_at": "2024-01-01T00:00:00+00:00"
}
```

**Required fields from provider:**
- `description` (pull_request)
- `base_commit` (pull_request)
- `patch` (pull_request)
- `repo_url` (repository)

## Test Field Format

For the DPAIA generator to extract test information, include markers in your PR body:

```markdown
## Summary
Fixed the null pointer exception in Parser.

## FAIL_TO_PASS
["com.example.ParserTest.testNullInput", "com.example.ParserTest.testEmptyInput"]

## PASS_TO_PASS
["com.example.ParserTest.testValidInput"]
```

Supported formats:
- JSON arrays: `FAIL_TO_PASS: ["test1", "test2"]`
- Comma-separated: `FAIL_TO_PASS: test1, test2`
- Markdown headers with content below

## Examples

### Generate from specific PRs

```bash
export GITHUB_TOKEN=your_token

ee-dataset generate \
    -p github_pull_requests \
    -g dpaia_jvm \
    -s '{"resource": "pull_requests", "filters": {"repo": "apache/kafka", "pr_numbers": [14521, 14498]}}' \
    --out kafka_bugs.jsonl
```

### Generate from labeled PRs

```yaml
# verified_bugs.yaml
resource: pull_requests
filters:
  repo: apache/kafka
  state: closed
  labels:
    - bug
    - verified
limit: 50
```

```bash
ee-dataset generate \
    -p github_pull_requests \
    -g dpaia_jvm \
    -s verified_bugs.yaml \
    --out kafka_verified_bugs.jsonl
```

### Using template variables

```yaml
# template_config.yaml
provider: github_pull_requests
generator: dpaia_jvm

selection:
  resource: pull_requests
  filters:
    repo: "{{ org }}/{{ project }}"
    state: {{ state | default('closed') }}
  limit: {{ limit | default(10) }}

output:
  path: datasets/{{ org }}_{{ project }}.jsonl
```

```bash
ee-dataset -c template_config.yaml \
    -S org=apache \
    -S project=kafka \
    -S limit=50 \
    generate
```

### Generate from multiple repositories

```yaml
# multi_repo.yaml
provider: github_pull_requests
generator: dpaia_jvm

selection:
  resource: pull_requests
  filters:
    repos:
      - apache/kafka
      - apache/flink
      - apache/spark
    state: closed
  limit: 100

output:
  path: datasets/apache_combined.jsonl
```

### Using wildcard patterns

```yaml
# wildcard_config.yaml
provider: github_pull_requests
generator: dpaia_jvm

selection:
  resource: pull_requests
  filters:
    repo: "apache/kafka-*"    # Matches kafka-clients, kafka-streams, etc.
    state: closed
  limit: 50

output:
  path: datasets/kafka_ecosystem.jsonl
```

### Using GitHub search query

```yaml
# search_config.yaml
provider: github_pull_requests
generator: dpaia_jvm

selection:
  resource: pull_requests
  filters:
    query: "is:pr is:merged label:bug repo:apache/kafka merged:2024-01-01..2024-12-31"
  limit: 100

output:
  path: datasets/kafka_bugs_2024.jsonl
```

### Output as JSON array

```bash
ee-dataset generate \
    -p github_pull_requests \
    -g dpaia_jvm \
    -s selection.yaml \
    --out dataset.json \
    --format json
```

## Import Command

The `import` command group imports HuggingFace datasets into a GitHub organization as PRs with structured metadata, labels, and project assignments.

### Usage

```bash
# Run the import pipeline
ee-dataset --config specs/import-swe-bench-pro.yaml import run

# Preview without making changes
ee-dataset --config specs/import-swe-bench-pro.yaml import dry-run

# Check import progress
ee-dataset --config specs/import-swe-bench-pro.yaml import status

# Reset a specific item for re-import
ee-dataset --config specs/import-swe-bench-pro.yaml import reset -i django__django-16255
```

### Import Config Structure

```yaml
provider:
  name: huggingface_dataset
  options:
    dataset_name: "ScaleAI/SWE-bench_Pro"
    split: test
    hf_token: ${HF_TOKEN:-}

generator:
  name: github_pr_importer
  options:
    target_org: dpaia
    github_token: ${GITHUB_TOKEN}
    dataset_label: swe-bench-pro
    state_file: ".state/swe-bench-pro.json"
    inter_operation_delay: 1.0

    # PR title: Jinja2 template with item fields as variables
    pr_title_template: "[{{ dataset_label }}] {{ problem_statement | first_sentence | truncate_title }}"

    # PR body: Jinja2 template with item fields as variables
    # Use {{ metadata(key=value, ...) }} to embed a <!--METADATA--> block
    pr_body_template: |
      ## Problem Statement

      {{ problem_statement | default("(no description)") }}

      {% if hints_text %}
      ## Hints

      {{ hints_text }}
      {% endif %}

      {{ metadata(instance_id=instance_id, repo=repo, base_commit=base_commit,
                   version=version, dataset="swe-bench-pro") }}

    # Labels: static values and Jinja2 templates resolved per-item
    labels:
      - swe-bench-pro
      - "{{ repo_language }}"
      - "{{ issue_categories }}"

    # Repo topics: set on forked repositories
    repo_topics:
      - swe-bench-pro
      - "{{ repo_language }}"

    # GitHub Projects V2: auto-create if needed
    projects:
      - name: "SWE Pro"
        scope: all
      - name: "{{ repo_language }}"
        scope: language

selection:
  resource: dataset_items
  filters: {}

output:
  format: jsonl
  path: results/swe-bench-pro-import.jsonl
```

### Jinja2 Templates in Generator Options

Labels, repo topics, and project names support Jinja2 `{{ }}` syntax for dynamic values resolved from each dataset item. The legacy `from:field_name` syntax is also supported for backward compatibility.

**Built-in filters** available in all templates:

| Filter | Description | Example |
|--------|-------------|---------|
| `first_sentence` | Extract first sentence (up to `. ` or newline) | `{{ text \| first_sentence }}` |
| `truncate_title` | Truncate to GitHub's 256-char title limit | `{{ text \| truncate_title }}` |
| `default(val)` | Fallback value for empty/missing fields | `{{ field \| default("N/A") }}` |

**Dynamic values** are expanded: if a field contains a JSON array (e.g. `["bug", "feature"]`), each element becomes a separate label/topic. Values are normalized to lowercase with spaces replaced by hyphens.

### Import State

The importer maintains a JSON state file to track which items have been imported. On subsequent runs, unchanged items are skipped. Use `import reset -i <id>` to force re-import of a specific item.

## Project Structure

```
ee-bench/
├── packages/
│   ├── ee_bench_generator/     # Core framework
│   │   ├── metadata.py         # Data types (FieldDescriptor, Selection, etc.)
│   │   ├── interfaces.py       # Provider and Generator ABCs
│   │   ├── engine.py           # DatasetEngine orchestration
│   │   ├── loader.py           # Plugin discovery
│   │   ├── matcher.py          # Compatibility validation
│   │   └── templates.py        # Jinja2 template rendering (render_template)
│   │
│   ├── ee_bench_cli/           # CLI tool
│   │   ├── cli.py              # Main entry point (--set option)
│   │   ├── commands/           # CLI commands (generate, import, config, etc.)
│   │   ├── config_parser.py    # YAML + Jinja2 config handling
│   │   └── output.py           # Output formatting
│   │
│   ├── ee_bench_github/        # GitHub providers
│   │   ├── api.py              # GitHub API client
│   │   ├── pattern_matcher.py  # Wildcard pattern matching
│   │   ├── issues_provider.py
│   │   └── pull_requests_provider.py
│   │
│   ├── ee_bench_dpaia/         # DPAIA generator
│   │   └── generator.py
│   │
│   ├── ee_bench_huggingface/   # HuggingFace dataset provider
│   │   └── provider.py
│   │
│   └── ee_bench_importer/      # GitHub PR importer generator
│       ├── generator.py        # GitHubPRImporterGenerator
│       ├── pr_body.py          # PR body/title template rendering + metadata
│       ├── patch_applier.py    # Git Data API patch application
│       ├── project_manager.py  # GitHub Projects V2 management
│       └── sync_state.py       # Import state tracking
│
├── specs/                      # Import spec YAML files
└── pyproject.toml             # Workspace configuration
```

## Creating Custom Plugins

### Custom Provider

```python
from ee_bench_generator import Provider
from ee_bench_generator.metadata import Context, FieldDescriptor, ProviderMetadata

class MyProvider(Provider):
    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="my_provider",
            sources=["my_source"],
            provided_fields=[
                FieldDescriptor("field_name", "my_source", description="..."),
            ],
        )

    def prepare(self, **options):
        # Initialize connections, auth, etc.
        pass

    def get_field(self, name: str, source: str, context: Context):
        # Return field value
        pass

    def iter_items(self, context: Context):
        # Yield items to process
        yield {"id": 1, ...}
```

Register in `pyproject.toml`:
```toml
[project.entry-points."ee_bench_generator.providers"]
my_provider = "my_package:MyProvider"
```

### Custom Generator

```python
from ee_bench_generator import Generator, Provider
from ee_bench_generator.metadata import Context, FieldDescriptor, GeneratorMetadata

class MyGenerator(Generator):
    @property
    def metadata(self) -> GeneratorMetadata:
        return GeneratorMetadata(
            name="my_generator",
            required_fields=[
                FieldDescriptor("field_name", "source"),
            ],
            optional_fields=[],
        )

    def output_schema(self) -> dict:
        return {"type": "object", "properties": {...}}

    def generate(self, provider: Provider, context: Context):
        for item in provider.iter_items(context):
            # Build record from provider fields
            yield {"field": provider.get_field("field_name", "source", context)}
```

Register in `pyproject.toml`:
```toml
[project.entry-points."ee_bench_generator.generators"]
my_generator = "my_package:MyGenerator"
```

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Run tests
uv run pytest -v

# Run specific test file
uv run pytest packages/ee_bench_github/tests/test_api.py -v
```

## License

MIT
