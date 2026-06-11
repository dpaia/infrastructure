# DPAIA Dataset Format

This document describes the format of a DPAIA evaluation dataset — how a datapoint is
laid out across the repository, its branches, and the pull request that ties them together.

A **datapoint** is one evaluation instance: a source PR in a `dpaia/*` repository paired
with `.ee-bench/` configuration that defines how to build the project, run its tests, and
validate a code change. The only supported evaluation type today is **codegen**.

The format separates two concerns:

- **Reusable scaffolding** — how to build and evaluate *any* change in this repo. Lives on
  the **default branch**.
- **The datapoint itself** — the specific problem, its gold fix, and the tests that prove
  it. Lives in a **PR branch**.

## Repository layout

The default branch holds the shared scaffolding that every datapoint inherits. It is stable
— datapoint PRs do not modify it.

```
.ee-bench/codegen/
├── metadata.json                # Base config defaults (no per-datapoint expected tests)
├── environment/
│   └── Dockerfile               # Builds the test environment (clone + deps), linux/amd64
└── eval/
    ├── run.sh                   # Evaluation entry point (two-phase test runner)
    └── scripts/
        ├── ee_bench_eval.py     # Language-independent result emitter (schema v2.0)
        └── ee_bench_parser_*.py # Language-specific test parser (junit / trx)
```

## Branches

A datapoint is anchored on two states of the project:

- **Base branch** — the state of the project **before the agent receives any task**: the
  unsolved problem. This is what the agent starts from. Tests covering the change are
  expected to fail here.
- **Solution branch** — the base state **plus the gold fix**: the source change the agent
  is expected to produce, together with the tests that prove it.

The base branch defines the starting point; the solution branch defines the target. The
difference between them, plus the metadata, is the entire datapoint.

A branch carries **only what is specific to this problem** — never the shared scaffolding
again. In practice it touches just:

1. `.ee-bench/codegen/metadata.json` — an override filling in the `expected` test arrays.
2. The gold source change — the production-code fix.
3. The test change — new or modified tests that prove the fix.

The build automatically splits the diff between base and solution into:

- **Gold patch** (`verify/patch.diff`) — source/production code. *What the AI must produce.*
- **Test patch** (`eval/test_patch.diff`) — test files. *Applied to verify the AI's solution.*

Files are classified by path heuristics (`/test/`, `*Test.*`, `test_*.*`, …). Files under
`.ee-bench/` are excluded from both patches. Override classification with
`patch.test_patterns` / `patch.source_patterns` in `metadata.json` for non-standard layouts.

> A branch **may** override scaffolding files when a tricky case requires it, but keep the
> override minimal — the smaller the diff, the easier the datapoint is to review and reproduce.

## metadata.json

`metadata.json` defines the datapoint's identity and its expected test outcomes. All fields
are optional; the base defaults live on the default branch and the datapoint branch overrides
only what it needs. The fields also become **template variables** (`{{ instance.<field> }}`)
available in `Dockerfile` and `run.sh`.

### Common fields
Keep in mind, it's a JSON schema. Fields with dots mean nested structures, not the field names.

| Field                           | Type     | Description                                                                                               |
|---------------------------------|----------|-----------------------------------------------------------------------------------------------------------|
| `instance_id`                   | string   | By default, datapoint id is generated as repo_name_<RT_number>, but using this field you can override it. |
| `version`                       | string   | Schema version (default `"1.0"`)                                                                          |
| `benchmark_type`                | string   | Evaluation type (default `"codegen"`)                                                                     |
| `language`                      | string   | Programming language (`"java"`, `"csharp"`, `"python"`, …) — exported as a tag                            |
| `environment.project_root`      | string   | Working directory inside the container (default `/repo`)                                                  |
| `environment.docker.run_params` | object   | Extra `docker run` settings (`privileged`, `network`, `volumes`, `environment`)                           |
| `expected.fail_to_pass`         | string[] | Tests that fail on the base state and pass after the gold fix                                             |
| `expected.pass_to_pass`         | string[] | Tests that pass before and after — regression guard (`["*"]` = all)                                       |
| `expected.fail_to_fail`         | string[] | Tests expected to fail both before and after (use sparingly)                                              |
| `patch.test_patterns`           | string[] | Globs forcing files to be classified as tests                                                             |
| `patch.source_patterns`         | string[] | Globs forcing files to be classified as source (highest priority)                                         |

### The `expected` arrays

These are the evaluation knobs that define what "solved" means:

- **`fail_to_pass`** — tests that fail on the base state and pass after the fix (proves the
  fix works). Empty is valid if the datapoint verifies via `pass_to_pass` alone.
- **`pass_to_pass`** — tests that pass before and after (proves the fix breaks nothing).
- **`fail_to_fail`** — known-failing tests that should stay failing.

### Minimal example

```json
{
  "language": "csharp",
  "expected": {
    "fail_to_pass": ["Moq.Tests.Regressions.IssueReportsFixture.Issue1259"],
    "pass_to_pass": ["Moq.Tests.MatcherAttributeFixture.TypedMatcherDoesNotMismatch"]
  }
}
```

## Pull request

The PR ties the datapoint together: it points from the solution state at the base state and
carries the gold change.

**The PR description is the problem statement, and nothing else** — it is written as a real
issue or feature request, exactly as the agent sees the task. Everything else that the
dataset needs (expected tests, language, environment, hints, requirements) is committed
through `metadata.json`, not the PR body. No ee-bench boilerplate appears in the title or
description.

## Dockerfile

The Dockerfile sets up the build and test environment. It lives on the default branch under
`.ee-bench/codegen/environment/` and is rendered as a Jinja2 template before use, so it can
reference any `metadata.json` field as `{{ instance.<field> }}`. It typically:

1. Clones the repository at the specified `base_commit`.
2. Installs all dependencies needed to build and run tests.
3. Targets the `linux/amd64` platform.

### Template variables

| Variable                      | Description                                         |
|-------------------------------|-----------------------------------------------------|
| `{{ instance.repo_url }}`     | Repository clone URL                                |
| `{{ instance.base_commit }}`  | Base commit SHA                                     |
| `{{ instance.head_commit }}`  | Head commit SHA                                     |
| `{{ instance.owner }}`        | Repository owner                                    |
| `{{ instance.repo_name }}`    | Repository name                                     |
| `{{ instance.repo }}`         | `owner/repo_name`                                   |
| `{{ instance.project_root }}` | Docker working directory (from metadata or `/repo`) |
| `{{ instance.instance_id }}`  | Datapoint identifier                                |
| `{{ instance.<field> }}`      | Any top-level field from `metadata.json`            |
