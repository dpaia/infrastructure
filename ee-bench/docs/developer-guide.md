# Developer Guide

This guide covers how to extend the ee-bench dataset toolkit by creating custom providers, generators, and specification files.

## Architecture Overview

### Plugin System

The toolkit uses an abstract plugin system built on two base classes:

- **Provider** (`ee_bench_generator.interfaces.Provider`) — fetches data from external sources (GitHub, HuggingFace, etc.) and exposes it through a field-based interface.
- **Generator** (`ee_bench_generator.interfaces.Generator`) — consumes fields from a provider and produces output dataset records.

Plugins are discovered at runtime via Python entry points (`importlib.metadata`). Each plugin package registers its classes under the `ee_bench_generator.providers` or `ee_bench_generator.generators` entry point groups.

### Data Flow

```
Selection criteria
       |
       v
Provider.iter_items(context) -----> yields items (dicts)
       |
       v                     for each item:
Provider.get_field(name, source, context) <--- Generator requests fields
       |
       v
Generator.generate(provider, context) -----> yields output records
       |
       v
Output (JSONL / JSON / YAML)
```

1. **Selection** — defines what items to process (resource type, filters, limit).
2. **Provider.iter_items()** — the primary provider iterates over matching items.
3. **Generator.generate()** — for each item, the generator requests fields from the provider via `get_field(name, source, context)` and produces output records.

### Field Routing

Fields are identified by `(name, source)` pairs. For example, `("description", "pull_request")` is a different field from `("description", "issue")`. This is expressed via `FieldDescriptor`:

```python
from ee_bench_generator.metadata import FieldDescriptor

FieldDescriptor(
    name="description",
    source="pull_request",
    required=True,
    description="PR body text",
)
```

The `source` parameter is optional (defaults to `""`). When omitted, the field is matched by name only, regardless of which source provides it:

```python
# Source-less: matches any provider that has a "patch" field
FieldDescriptor("patch")

# Explicit source: only matches providers that have "patch" from "pull_request"
FieldDescriptor("patch", source="pull_request")
```

When `CompositeProvider` resolves a source-less field, it discovers the concrete source from the routing table and forwards it to the owning provider, so concrete providers always receive a non-empty source.

### Validation

Before generation starts, the engine validates that the provider can satisfy all required fields declared by the generator. This is done by `validate_compatibility()` in `matcher.py`. When a required field name appears with multiple sources (e.g., `description` from both `pull_request` and `issue`), the provider only needs to satisfy at least one source variant.

Use `--defer-validation` for providers that discover fields dynamically during `prepare()` (e.g., HuggingFace datasets).

---

## Creating a Provider

### The Provider ABC

Subclass `ee_bench_generator.interfaces.Provider` and implement four methods:

```python
from ee_bench_generator.interfaces import Provider
from ee_bench_generator.metadata import Context, FieldDescriptor, ProviderMetadata

class MyProvider(Provider):
    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="my_provider",
            sources=["my_source"],
            provided_fields=[
                FieldDescriptor("title", source="my_source", description="Item title"),
                FieldDescriptor("body", source="my_source", description="Item body"),
            ],
        )

    def prepare(self, **options) -> None:
        """Called once before data fetching. Configure auth, clients, caches."""
        self._token = options.get("token", "")
        # Set up API client, caching, etc.

    def get_field(self, name: str, source: str, context: Context):
        """Return a single field value for the current item."""
        item = context.current_item
        if name == "title":
            return item.get("title", "")
        if name == "body":
            return item.get("body", "")

    def iter_items(self, context: Context):
        """Yield items matching the selection criteria."""
        filters = context.selection.filters
        for item in self._fetch_items(filters):
            yield {"id": item["id"], "title": item["title"], "body": item["body"]}
```

### ProviderMetadata

```python
ProviderMetadata(
    name="my_provider",           # Unique name (matches entry point key)
    sources=["my_source"],        # List of data sources this provider supports
    provided_fields=[...],        # List of FieldDescriptor objects
)
```

### Primary vs. Enrichment Providers

- **Primary providers** drive iteration — their `iter_items()` yields items for the pipeline. Exactly one provider must have `role: primary` in a multi-provider config.
- **Enrichment providers** receive data from other providers via `item_mapping` and add additional fields. Their `iter_items()` should raise `ProviderError`.

Enrichment providers receive mapped data through `context.current_item`, which is constructed from `item_mapping` Jinja2 templates that reference other providers' fields.

### Real Implementation Examples

| Provider | Role | File |
|----------|------|------|
| `GitHubPullRequestsProvider` | Primary | `ee_bench_github/pull_requests_provider.py` |
| `GitHubIssuesProvider` | Primary | `ee_bench_github/issues_provider.py` |
| `HuggingFaceDatasetProvider` | Primary | `ee_bench_huggingface/provider.py` |
| `MetadataProvider` | Enrichment | `ee_bench_metadata/provider.py` |
| `PatchSplitterProvider` | Enrichment | `ee_bench_patch_splitter/provider.py` |
| `RunScriptsProvider` | Enrichment | `ee_bench_run_scripts/provider.py` |

---

## Creating a Generator

### The Generator ABC

Subclass `ee_bench_generator.interfaces.Generator` and implement two methods:

```python
from ee_bench_generator.interfaces import Generator, Provider
from ee_bench_generator.metadata import Context, FieldDescriptor, GeneratorMetadata

class MyGenerator(Generator):
    @property
    def metadata(self) -> GeneratorMetadata:
        return GeneratorMetadata(
            name="my_generator",
            required_fields=[
                FieldDescriptor("title", source="my_source", description="Item title"),
                FieldDescriptor("body", source="my_source", description="Item body"),
            ],
            optional_fields=[
                FieldDescriptor("labels", source="my_source", required=False,
                                description="Item labels"),
            ],
        )

    def generate(self, provider: Provider, context: Context):
        """Generate output records by requesting fields from the provider."""
        for item in provider.iter_items(context):
            item_context = Context(
                selection=context.selection,
                options=context.options,
                current_item=item,
            )

            title = provider.get_field("title", "my_source", item_context)
            body = provider.get_field("body", "my_source", item_context)

            yield {
                "id": item.get("id", ""),
                "content": f"{title}\n\n{body}",
            }
```

### GeneratorMetadata

```python
GeneratorMetadata(
    name="my_generator",          # Unique name (matches entry point key)
    required_fields=[...],        # Fields that must be available
    optional_fields=[...],        # Fields used if available (default_factory=list)
)
```

`FieldDescriptor` signature: `FieldDescriptor(name, source="", required=True, description="")`. When `source` is omitted, the field is matched by name only.

### Multi-Source Fields

A generator can declare the same field name from multiple sources. The validation system treats this as "at least one source must be satisfied":

```python
required_fields=[
    FieldDescriptor("description", source="pull_request"),
    FieldDescriptor("description", source="issue"),
]
```

A simpler alternative when the generator doesn't care about the source is to omit it entirely:

```python
required_fields=[
    FieldDescriptor("description"),  # matches any provider with a "description" field
]
```

At runtime, the generator tries the primary source first and falls back:

```python
def _get_field_with_fallback(self, provider, name, primary_source, context, default):
    fallback = "issue" if primary_source == "pull_request" else "pull_request"
    for source in [primary_source, fallback]:
        if provider.metadata.can_provide(name, source):
            try:
                value = provider.get_field(name, source, context)
                if value:
                    return value
            except Exception:
                pass
    return default
```

### Real Implementation Examples

| Generator | File |
|-----------|------|
| `DpaiaJvmGenerator` | `ee_bench_dpaia/generator.py` |
| `DpaiaSweProGenerator` | `ee_bench_dpaia/generator.py` |
| `GitHubPRImporterGenerator` | `ee_bench_importer/generator.py` |
| `GitHubAttachmentGenerator` | `ee_bench_run_scripts/attachment_generator.py` |
| `AttachmentExportGenerator` | `ee_bench_run_scripts/attachment_export_generator.py` |

---

## Registering Plugins

### Entry Points in pyproject.toml

Each plugin package declares entry points under the appropriate group:

```toml
[project.entry-points."ee_bench_generator.providers"]
my_provider = "my_package:MyProvider"

[project.entry-points."ee_bench_generator.generators"]
my_generator = "my_package:MyGenerator"
```

The entry point key (e.g., `my_provider`) becomes the plugin name used in config files and CLI options.

### Adding to the Workspace

1. Create the package under `ee-bench/packages/`:

```
ee-bench/packages/ee_bench_myplugin/
  pyproject.toml
  src/
    ee_bench_myplugin/
      __init__.py
      provider.py       # or generator.py
```

2. Add to root `ee-bench/pyproject.toml`:

```toml
[project]
dependencies = [
    # ... existing deps ...
    "ee_bench_myplugin",
]

[tool.uv.sources]
ee_bench_myplugin = { workspace = true }
```

3. Run `uv sync` to install.

### Package Structure Template

Use `ee_bench_patch_splitter` as a minimal template:

```toml
# pyproject.toml
[project]
name = "ee_bench_myplugin"
version = "0.1.0"
description = "My custom plugin for ee_bench"
requires-python = ">=3.11"
dependencies = [
    "ee_bench_generator",
]

[project.entry-points."ee_bench_generator.providers"]
my_provider = "ee_bench_myplugin:MyProvider"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ee_bench_myplugin"]
```

Verify registration with `ee-dataset list`.

---

## Writing Specification Files (YAML)

Specification files define the complete pipeline configuration: providers, generators, selection criteria, and output settings.

### Singular Format

For simple single-provider, single-generator pipelines:

```yaml
provider:
  name: github_pull_requests
  options:
    token: ${GITHUB_TOKEN}

generator:
  name: dpaia_jvm
  options:
    version: "1"

selection:
  resource: pull_requests
  filters:
    repo: "apache/kafka"
    pr_numbers: [42]

output:
  format: jsonl
  path: out.jsonl
```

### Plural Format

For multi-provider and/or multi-generator pipelines:

```yaml
providers:
  - name: github             # Instance name (unique within the spec)
    type: github_pull_requests  # Plugin type (entry point name)
    role: primary
    options:
      token: ${GITHUB_TOKEN}

  - name: metadata
    type: metadata
    item_mapping:             # Jinja2 templates referencing other providers
      text: "{{ providers.github.description }}"
    options:
      fields: [instance_id, repo, base_commit]

generators:
  - name: exporter
    type: dpaia_swe_pro
    output:
      format: jsonl
      path: datasets/export.jsonl

  - name: attachment_downloader
    type: attachment_export
    options:
      github_token: ${GITHUB_TOKEN}
      output_dir: "attachments"
    output:
      format: jsonl
      path: results/attachments.jsonl

selection:
  resource: pull_requests
  filters:
    repos: ["dpaia/*"]
    labels: [swe-bench-pro]
    state: open
```

### Provider Config Keys

| Key | Required | Description |
|-----|----------|-------------|
| `name` | Yes | Unique instance identifier within the spec |
| `type` | Yes (plural) | Plugin type (entry point name). In singular format, `name` is the plugin type. |
| `role` | No | `"primary"` for the driving provider (exactly one required in plural format) |
| `options` | No | Provider-specific configuration passed to `prepare()` |
| `item_mapping` | No | Dict of `field: "{{ providers.<name>.<field> }}"` Jinja2 templates for enrichment |

### Generator Config Keys

| Key | Required | Description |
|-----|----------|-------------|
| `name` | Yes | Unique instance identifier / plugin type |
| `type` | Yes (plural) | Plugin type (entry point name) |
| `options` | No | Generator-specific options |
| `output` | No | Per-generator output config (`format`, `path`) |

### Selection Block

```yaml
selection:
  resource: pull_requests      # Resource type: "pull_requests", "issues", "dataset_items"
  filters:
    repo: "owner/repo"         # Single repo
    repos: ["owner/repo1"]     # Multiple repos (supports wildcards: "org/*")
    pr_numbers: [42, 43]       # Specific items
    labels: ["bug"]            # Filter by labels
    state: open                # State filter
    query: "is:pr label:bug"   # GitHub search query (mutually exclusive with repo/repos)
  limit: 10                    # Max items to process
```

### Output Block

```yaml
output:
  format: jsonl                # "jsonl", "json", or "yaml"
  path: out.jsonl              # Output file path
```

### Validation Block

```yaml
validation:
  defer: true                  # Defer compatibility checks until after prepare()
```

### Environment Variable Substitution

Use `${VAR}` or `${VAR:-default}` anywhere in YAML values:

```yaml
options:
  token: ${GITHUB_TOKEN}
  hf_token: ${HF_TOKEN:-}         # Empty string default
  org: ${TARGET_ORG:-dpaia}        # "dpaia" default
```

### Template Variables (--set / -S)

Template variables are substituted before YAML parsing using Jinja2:

```yaml
selection:
  filters:
    repo: "{{ ORGANIZATION }}/{{ REPOSITORY }}"
    issue_numbers: [{{ ISSUE_NUMBER }}]
```

Run with:

```bash
ee-dataset --config spec.yaml -S ORGANIZATION=apache -S REPOSITORY=kafka -S ISSUE_NUMBER=12345 generate
```

### Jinja2 Templates in Config

Generator options can use Jinja2 templates that are rendered with dataset item fields as variables:

```yaml
options:
  pr_title_template: "[{{ dataset_label }}] {{ problem_statement | first_sentence | truncate_title }}"
  labels:
    - swe-bench-pro
    - "{{ repo_language }}"
```

---

## Writing Pipelines (Python DSL)

The `ee_bench_dsl` package provides a fluent Python API for building pipelines programmatically.

### Pipeline Builder

```python
from ee_bench_dsl import Pipeline, from_items, each, env

# Basic pipeline
Pipeline() \
    .provider(from_items([{"id": 1, "text": "hello"}, {"id": 2, "text": "world"}])) \
    .generator(each(lambda item, ctx: {"id": item["id"], "upper": item["text"].upper()})) \
    .select("items") \
    .output("results.jsonl") \
    .run()
```

### Key Methods

| Method | Description |
|--------|-------------|
| `.provider(name_or_instance, type=, role=, item_mapping=, **options)` | Add a provider (by name or instance) |
| `.generator(name_or_instance, type=, output=, **options)` | Add a generator (by name or instance) |
| `.select(resource, filters=, limit=, **kw_filters)` | Set selection criteria |
| `.filter(**kw)` | Add/merge filters |
| `.limit(n)` | Set item limit |
| `.output(path, fmt="jsonl")` | Set output path and format |
| `.transform(fn)` | Append a post-processing function |
| `.defer_validation()` | Defer compatibility checks |
| `.run()` | Execute and write to output; returns record count |
| `.iter()` | Execute and return lazy record iterator |
| `.collect()` | Execute and return list of all records |

### from_items() — Inline Data Provider

```python
from ee_bench_dsl import from_items

provider = from_items([
    {"id": 1, "text": "hello"},
    {"id": 2, "text": "world"},
])
```

Also accepts a callable: `from_items(lambda: load_data())`.

### each() — Per-Item Generator

```python
from ee_bench_dsl import each

generator = each(lambda item, ctx: {
    "id": item["id"],
    "processed": item["text"].upper(),
})
```

Return `None` to skip an item.

### env() — Environment Variables

```python
from ee_bench_dsl import env

token = env("GITHUB_TOKEN")               # Raises ValueError if missing
token = env("GITHUB_TOKEN", default="")   # Empty string if missing
```

### Multi-Provider / Multi-Generator

```python
Pipeline() \
    .provider("huggingface", type="huggingface_dataset", role="primary",
              dataset_name="ScaleAI/SWE-bench_Pro", split="test") \
    .provider("metadata", type="metadata",
              item_mapping={"text": "{{ providers.huggingface.description }}"},
              fields=["instance_id", "repo"]) \
    .generator("exporter", type="dpaia_swe_pro", output="export.jsonl") \
    .generator("attachments", type="attachment_export", output="attachments.jsonl") \
    .defer_validation() \
    .select("dataset_items") \
    .run()
```

### Transforms

Apply post-processing to output records:

```python
Pipeline() \
    .provider(from_items(data)) \
    .generator(each(lambda item, ctx: item)) \
    .select("items") \
    .transform(lambda r: {**r, "tag": "marked"}) \
    .transform(lambda r: r if r["score"] > 0.5 else None) \
    .collect()
```

### Running Pipeline Scripts

Pipeline scripts are Python files executed via the CLI:

```bash
ee-dataset run-script scripts/my_pipeline.py
ee-dataset run-script scripts/my_pipeline.py -S GITHUB_TOKEN=xxx -S ORG=apache
```

The runner looks for a `main()` function or a `pipeline` variable with a `.run()` method.

---

## Available Providers Reference

### github_pull_requests

| | |
|---|---|
| **Entry point** | `github_pull_requests` |
| **Class** | `GitHubPullRequestsProvider` |
| **Package** | `ee_bench_github` |
| **Role** | Primary |
| **Sources** | `pull_request`, `repository` |

**Provided fields:**

| Field | Source | Description |
|-------|--------|-------------|
| `description` | `pull_request` | PR body text |
| `title` | `pull_request` | PR title |
| `labels` | `pull_request` | List of label names |
| `number` | `pull_request` | PR number |
| `base_commit` | `pull_request` | Base branch SHA |
| `head_commit` | `pull_request` | Head branch SHA |
| `commits` | `pull_request` | List of commit SHAs |
| `patch` | `pull_request` | Combined diff |
| `FAIL_TO_PASS` | `pull_request` | Parsed test field from body |
| `PASS_TO_PASS` | `pull_request` | Parsed test field from body |
| `metadata` | `pull_request` | Parsed `<!--METADATA-->` block |
| `repo_tree` | `repository` | List of file paths at base commit |
| `repo_url` | `repository` | Repository clone URL |

**Options:** `token`, `base_url` (default: `https://api.github.com`), `timeout` (default: 30)

**Selection filters:** `repo`, `repos` (supports wildcards), `pr_numbers`, `state`, `labels`, `query`

---

### github_issues

| | |
|---|---|
| **Entry point** | `github_issues` |
| **Class** | `GitHubIssuesProvider` |
| **Package** | `ee_bench_github` |
| **Role** | Primary |
| **Sources** | `issue`, `repository` |

**Provided fields:**

| Field | Source | Description |
|-------|--------|-------------|
| `description` | `issue` | Issue body text |
| `title` | `issue` | Issue title |
| `labels` | `issue` | List of label names |
| `number` | `issue` | Issue number |
| `commits` | `issue` | Linked commit SHAs (requires `fetch_commits: true`) |
| `base_commit` | `issue` | Parent of earliest commit (requires `fetch_commits: true`) |
| `patch` | `issue` | Combined diff from commits (requires `fetch_commits: true`) |
| `FAIL_TO_PASS` | `issue` | Tests from body/comments (requires `parse_comments: true`) |
| `PASS_TO_PASS` | `issue` | Tests from body/comments (requires `parse_comments: true`) |
| `build_system` | `repository` | Build system type (requires `detect_build_system: true`) |
| `repo_tree` | `repository` | List of file paths |
| `repo_url` | `repository` | Repository clone URL |

**Options:** `token`, `base_url`, `timeout`, `fetch_commits` (default: false), `parse_comments` (default: false), `detect_build_system` (default: false)

**Selection filters:** `repo`, `repos`, `issue_numbers`, `state`, `labels`

---

### huggingface_dataset

| | |
|---|---|
| **Entry point** | `huggingface_dataset` |
| **Class** | `HuggingFaceDatasetProvider` |
| **Package** | `ee_bench_huggingface` |
| **Role** | Primary |
| **Sources** | `dataset_item`, `dataset_metadata` |

**Provided fields:** Dynamically discovered from dataset columns at `prepare()` time. All columns are exposed as `dataset_item` source fields. Additionally provides `checksum` from `dataset_metadata` source.

**Options:** `dataset_name`, `dataset_path` (local file alternative), `split` (default: `test`), `hf_token`, `filters` (generic filter dict)

**Filter operators:** `eq`, `not_eq`, `in`, `not_in`, `contains`, `not_contains`, `regex`, `startswith`, `endswith`. Simple key-value filters use equality by default.

---

### metadata

| | |
|---|---|
| **Entry point** | `metadata` |
| **Class** | `MetadataProvider` |
| **Package** | `ee_bench_metadata` |
| **Role** | Enrichment only |
| **Sources** | Configurable (default: `pull_request`) |

Parses `<!--METADATA ... METADATA-->` blocks from text and exposes individual keys as fields.

**Provided fields:** Dynamic, based on the `fields` option. Each listed field name becomes a `FieldDescriptor`.

**Options:** `fields` (required list of metadata key names), `source` (default: `"pull_request"`)

**item_mapping:** Must receive `text` containing the metadata block, e.g.:
```yaml
item_mapping:
  text: "{{ providers.github.description }}"
```

---

### patch_splitter

| | |
|---|---|
| **Entry point** | `patch_splitter` |
| **Class** | `PatchSplitterProvider` |
| **Package** | `ee_bench_patch_splitter` |
| **Role** | Enrichment only |
| **Sources** | `pull_request`, `issue` |

Splits a unified diff into source-only and test-only portions using filename pattern matching.

**Provided fields:**

| Field | Source | Description |
|-------|--------|-------------|
| `patch` | `pull_request`, `issue` | Source-only diff (test files removed) |
| `test_patch` | `pull_request`, `issue` | Test-only diff |

**Options:** None.

**item_mapping:** Must receive `patch`, e.g.:
```yaml
item_mapping:
  patch: "{{ providers.github.patch }}"
```

---

### run_scripts

| | |
|---|---|
| **Entry point** | `run_scripts` |
| **Class** | `RunScriptsProvider` |
| **Package** | `ee_bench_run_scripts` |
| **Role** | Enrichment only |
| **Sources** | `run_scripts` |

Fetches run script and parser files from a GitHub repository.

**Provided fields:**

| Field | Source | Description |
|-------|--------|-------------|
| `run_script` | `run_scripts` | Content of `run_script.sh` |
| `parser_script` | `run_scripts` | Content of `parser.py` |
| `run_script_name` | `run_scripts` | Filename or empty string |
| `parser_name` | `run_scripts` | Filename or empty string |

**Options:** `repo` (default: `scaleapi/SWE-bench_Pro-os`), `github_token`, `scripts_dir` (default: `run_scripts`)

**item_mapping:** Must receive `instance_id`, e.g.:
```yaml
item_mapping:
  instance_id: "{{ providers.huggingface.instance_id }}"
```

---

## Available Generators Reference

### dpaia_jvm

| | |
|---|---|
| **Entry point** | `dpaia_jvm` |
| **Class** | `DpaiaJvmGenerator` |
| **Package** | `ee_bench_dpaia` |

Produces DPAIA-format dataset records for JVM projects. Supports both `pull_request` and `issue` sources with automatic fallback.

**Required fields:** `description` (pull_request or issue), `base_commit` (pull_request or issue), `patch` (pull_request or issue), `repo_url` (repository)

**Optional fields:** `instance_id`, `title`, `FAIL_TO_PASS`, `PASS_TO_PASS`, `hints_text`, `number`, `labels`, `test_patch`, `repo_tree`, `build_system`

**Output:** `instance_id`, `repo`, `base_commit`, `patch`, `test_patch`, `problem_statement`, `hints_text`, `FAIL_TO_PASS`, `PASS_TO_PASS`, `created_at`, `version`, `build_system`, `is_maven`, `issue_numbers`, `tags`

---

### dpaia_swe_pro

| | |
|---|---|
| **Entry point** | `dpaia_swe_pro` |
| **Class** | `DpaiaSweProGenerator` |
| **Package** | `ee_bench_dpaia` |

Produces records matching the original SWE-bench Pro dataset schema, round-tripping all metadata fields embedded during import.

**Required fields:** `description` (pull_request), `patch` (pull_request), `repo_url` (repository)

**Optional fields:** `title`, `instance_id`, `hints_text`, `test_patch`, plus all SWE-bench Pro metadata fields: `repo`, `base_commit`, `version`, `repo_language`, `FAIL_TO_PASS`, `PASS_TO_PASS`, `environment_setup_commit`, `requirements`, `interface`, `issue_specificity`, `issue_categories`, `dockerhub_tag`, `before_repo_set_cmd`, `selected_test_files_to_run`, `created_at`, `checksum`, `dataset`, `run_script_name`, `parser_name`

**Output:** Full SWE-bench Pro schema with all metadata fields preserved.

---

### github_pr_importer

| | |
|---|---|
| **Entry point** | `github_pr_importer` |
| **Class** | `GitHubPRImporterGenerator` |
| **Package** | `ee_bench_importer` |

Imports dataset items into GitHub as pull requests — creates forks, branches, applies patches, and creates PRs with structured metadata.

**Required fields:** `instance_id` (dataset_item), `repo` (dataset_item), `base_commit` (dataset_item), `patch` (dataset_item), `problem_statement` (dataset_item), `checksum` (dataset_metadata)

**Optional fields:** `test_patch`, `hints_text`, `repo_language`, `version` (all from dataset_item)

**Key options:** `target_org`, `github_token`, `dataset_label`, `state_file`, `dry_run`, `inter_operation_delay`, `pr_title_template`, `pr_body_template`, `labels`, `repo_topics`, `projects`, `repo_visibility`, `pr_state`

**Output:** `instance_id`, `status` (created/updated/skipped/error), `pr_url`, `pr_number`, `fork_repo`, `error`

---

### github_attachment

| | |
|---|---|
| **Entry point** | `github_attachment` |
| **Class** | `GitHubAttachmentGenerator` |
| **Package** | `ee_bench_run_scripts` |

Uploads attachment files (run scripts, parsers) to PR branches in GitHub.

**Required fields:** `instance_id` (dataset_item), `repo` (dataset_item)

**Optional fields:** `run_script`, `parser_script`, `run_script_name`, `parser_name` (all from run_scripts)

**Key options:** `target_org`, `github_token`, `dataset_label`, `attachment_dir`, `state_file`, `inter_operation_delay`, `dry_run`

**Output:** `instance_id`, `status` (attached/skipped/error), `files`, `pr_url`, `error`

---

### attachment_export

| | |
|---|---|
| **Entry point** | `attachment_export` |
| **Class** | `AttachmentExportGenerator` |
| **Package** | `ee_bench_run_scripts` |

Downloads attachment files from PR branches to local directories.

**Required fields:** `repo_url` (repository)

**Optional fields:** `instance_id` (pull_request), `run_script_name` (pull_request), `parser_name` (pull_request)

**Key options:** `github_token`, `dataset_label`, `attachment_dir`, `output_dir`, `dry_run`

**Output:** `instance_id`, `status` (downloaded/no_attachments/error), `output_dir`, `files`, `error`
