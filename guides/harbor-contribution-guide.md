# Harbor Datapoint Contribution Guide

How to contribute an evaluation datapoint that runs on the
[Harbor](https://pypi.org/project/harbor/) framework — from a source PR in a
`dpaia/*` repository to a task you can evaluate locally with `ide-eval-harbor`.

## Introduction

A **Harbor datapoint** is an evaluation task: a source PR in a `dpaia/*`
repository, paired with a per-repository **Harbor task template** that lives in
the central [`dpaia/.dpaia_templates`](https://github.com/dpaia/.dpaia_templates)
repo. You open a normal PR that fixes an
issue or adds a feature; the pipeline renders the template with your PR's data,
validates the result with Harbor's oracle agent, and merges a complete Harbor
task into [`dpaia/dataset`](https://github.com/dpaia/dataset) under
`_harbor_converted/<language>/<repo>/<instance_id>/`.

Everything a contributor authors is one file — `.harbor/metadata.json` — plus,
optionally, a few file overrides. A Harbor template renders **byte-for-byte**
into the final task, so there is no hidden transformation to reason about.

**Pipeline at a glance:**

1. You open a PR in a `dpaia/*` repo. The PR body is the agent task; the diff
   contains a production-code change (the "gold" solution) and tests that gate
   it. The PR includes `.harbor/metadata.json`.
2. A reviewer moves the PR to **Review** on the
   [Code Generation](https://github.com/orgs/dpaia/projects/13) board.
3. The pipeline renders the template + your metadata into a Harbor task and
   validates it with the **oracle agent** (must reach reward 1). Result posted
   on the PR; **Verification** field flips to **Valid** or **Invalid**.
4. A reviewer moves the PR to **Verified**. The pipeline generates a dataset PR
   in `dpaia/dataset`, validates it, and auto-merges. Your PR reaches **Done**.
5. You run the merged task locally with `ide-eval-harbor` and inspect results.

For a complete real example, browse
[`dpaia/.dpaia_templates/harbor/dpaia/feature-service/`](https://github.com/dpaia/.dpaia_templates/tree/main/harbor/dpaia/feature-service)
(the template) alongside `dpaia/dataset/_harbor_converted/java/feature-service/`
(the tasks it produces, e.g. `dpaia__feature__service-245`).

## Prerequisites

- **`dpaia` org access** — source PRs must live under the `dpaia` GitHub
  organization.
- **Docker** — `linux/amd64` platform, for local evaluation.
- **`gh` CLI, authenticated** — with project-board read, Actions read, and
  workflow-dispatch permission on `dpaia/infrastructure`. Required so the local
  runner can resolve a project-board query into instance ids
  (see [Run the evaluation locally](#7-run-the-evaluation-locally)).
- **A clone of [`ide-eval-harbor`](https://github.com/JetBrains/ide-eval-harbor)** —
  the local Harbor eval runner.

## The Main Flow

### 1. Pick a project

Choose an existing repository in the [`dpaia`](https://github.com/dpaia)
organization. If the project you want is not in the org yet, fork it into
`dpaia`. Protect the default branch from direct pushes.

### 2. Check that a Harbor template exists

Look in [`dpaia/.dpaia_templates`](https://github.com/dpaia/.dpaia_templates)
for `harbor/dpaia/<repo>/`. If a template exists, you are ready to author a
datapoint — **every datapoint PR in a repo that has a template automatically
produces a Harbor task**.

If no template exists, create one first — see
[Template authoring](#template-authoring). This is a one-time setup per
repository.

### 3. Create the pull request

Open a PR whose diff contains both the production-code change that solves the
issue (the "gold patch") and the tests that verify it. Requirements:

- **Description = the agent task** — the PR body becomes the agent's
  `instruction.md`.
- **Verifying tests** — they become `fail_to_pass`: failing at the base commit,
  passing once the gold patch is applied.
- **Language label** — e.g. `Language: Java`. Exported as a keyword; the local
  runner filters on it.
- **Add the PR to the project [Code Generation](https://github.com/orgs/dpaia/projects/13)
  board.**
- **`.harbor/metadata.json`** — at minimum `language` and
  `expected.fail_to_pass`:

```json
{
  "language": "java",
  "expected": {
    "fail_to_pass": [
      "com.example.approvals.api.ApprovalPolicyControllerVersioningTest"
    ]
  }
}
```

Most datapoints need nothing more. The full field list is in the
[`.harbor/metadata.json` reference](#harbormetadatajson-reference); the
variables you can set are catalogued in
[`harbor/VARIABLES.md`](https://github.com/dpaia/.dpaia_templates/blob/main/harbor/VARIABLES.md),
and each template's `README.md` lists its baked defaults.

### 4. Move to "Review" and wait for Valid

Move the PR to **Review** on the board. The pipeline renders the template with
your PR's data and validates the task with the **oracle agent** (applies the
gold patch, must reach reward `1`). The **Verification** field flips to
**Valid** or **Invalid**, with a comment on the PR.

If **Invalid**, read the comment and linked run, fix, and push — new commits
reset the status and re-run verification.

### 5. Move to "Verified" and wait for Done

Move the PR to **Verified**. The pipeline generates a dataset PR in
`dpaia/dataset`, validates it, and auto-merges — your PR then reaches **Done**.
The task now lives at `_harbor_converted/<language>/<repo>/<instance_id>/` and
is ready to evaluate.

### 6. Clone and set up `ide-eval-harbor`

Clone [`ide-eval-harbor`](https://github.com/JetBrains/ide-eval-harbor) and do
first-time setup:

```bash
cp skills/run-harbor-eval/scripts/.env.local.example \
   skills/run-harbor-eval/scripts/.env.local
```

Fill in provider credentials and, if you plan to run with an IDE, the IDE
archive path. For running the agent inside a JetBrains IDE with MCP, and for
loading skills, see
[Running the evaluation with an IDE and skills](#running-the-evaluation-with-an-ide-and-skills)
and the canonical runbook,
[`ide-eval-harbor/README_RUN_EVAL.md`](https://github.com/JetBrains/ide-eval-harbor/blob/main/README_RUN_EVAL.md).

> Two things to know up front: **MCP configuration changes require rebuilding
> the IDE**, while **skills can be passed per run as `--skill` args or
> configured once via a profile** — no rebuild needed.

### 7. Run the evaluation locally

Point the runner at a **slice of the `dpaia` dataset selected by query**. The
wrapper resolves the project-board query to instance ids, exports the matching
Harbor task directories into a local cache, and runs them — no manual clone of
`dpaia/dataset` needed.

By query (e.g. all Java datapoints):

```bash
./skills/run-harbor-eval/scripts/harbor_eval.py --detach \
  --dpaia-query 'is:pr label:Spring repo:dpaia/saas-procurement' \
  --job-name my-java-run-$(date +%Y%m%d-%H%M%S)
```

Or run exactly your datapoint by instance id:

```bash
./skills/run-harbor-eval/scripts/harbor_eval.py --detach \
  --dpaia-instance-id dpaia__feature__service-245 \
  --job-name my-datapoint-run-$(date +%Y%m%d-%H%M%S)
```

The detached launcher prints the job name, PID, and log path. For agent/model
choices, profiles, and dry-run/preflight, see the
[Local eval deep-dive](#local-eval-deep-dive).

### 8. Analyze the results

Once the job finishes, inspect the reward and compare runs — see
[Comparing results with Harbor](#comparing-results-with-harbor). The
authoritative signal is the verifier reward (`1` = solved):

```bash
jq '.stats' jobs/<job-name>/result.json
cat jobs/<job-name>/<trial-name>/verifier/reward.txt
```

---

## Template authoring

A repository becomes "harbor-capable" when a template exists at
`harbor/dpaia/<repo>/` in
[`dpaia/.dpaia_templates`](https://github.com/dpaia/.dpaia_templates). This is a
one-time setup per repo. Read the
[`.dpaia_templates` README](https://github.com/dpaia/.dpaia_templates/blob/main/README.md)
for the full contract.

### What a template is

A template is a **real Harbor task with Jinja variables** — after rendering it
lands byte-for-byte in `dataset/_harbor_converted/`. It is a native Harbor
task, not a port of the EE-Bench eval pipeline (no `run.sh`, no
`ee_bench_*.py`). Layout:

```
harbor/dpaia/<repo>/
├── task.toml               # Jinja2-templated task config
├── README.md               # this template's baked defaults + link to VARIABLES.md
├── environment/
│   ├── Dockerfile          # Jinja2 ({{ instance.base_commit }}, …)
│   └── docker-compose.yaml # optional overlay (Testcontainers repos)
├── solution/
│   └── solve.sh            # applies /solution/patch.diff (author this)
└── tests/
    ├── test.sh             # verifier — writes /logs/verifier/reward.txt
    └── scripts/            # whatever test.sh needs
```

**Required files:** `task.toml`, `environment/Dockerfile`, `tests/test.sh`.
The verifier (`test.sh`) restores test sources to `{{ instance.base_commit }}`
so agent edits to tests don't count, applies `/tests/test_patch.diff` when
present, runs the expected tests, and always writes `1` or `0` to
`/logs/verifier/reward.txt`.

**Injected per datapoint — never author these:** `instruction.md` (from the PR
body), `solution/patch.diff` (gold patch), `tests/test_patch.diff` (test
patch). `solution/solve.sh` is authored in the template but injected as a
fallback if omitted.

### Generate a template with the skill

Use the `generate-harbor-template` skill from a `dpaia/.dpaia_templates`
checkout, run inside a checkout of the **target** repo:

```
/generate-harbor-template [--pr <N>] [--variant <name>] [--out <path-to-.dpaia_templates-checkout>]
```

- **Convert mode** — the repo already has `.ee-bench/codegen/`. Reuses its
  Dockerfile and build facts; emits a native Harbor verifier.
- **Analyze mode** — no `.ee-bench/`. Detects the build system
  (Gradle/Maven/npm/dotnet/pip) and instantiates a starter.
- `--pr <N>` runs a full end-to-end oracle check (expects reward 1) before you
  open the template PR.

The skill verifies the result (render check → docker build → oracle run), then
you open a PR against `dpaia/.dpaia_templates`.

### Named variants and per-PR overrides

- **Named variant** — a sibling template `harbor/dpaia/<repo>@<variant>/`,
  selected from a datapoint via `"templates": { "harbor": "harbor/dpaia/<repo>@<variant>" }`.
- **Per-PR `.harbor/` overrides** — files in your PR's `.harbor/` directory
  overlay the central template file-by-file. `.harbor/metadata.json` is data,
  not a template file, and is excluded from the overlay.

Template resolution order (highest first): PR `.harbor/` files →
`templates.harbor` reference → default `harbor/dpaia/<repo>/`. An explicit
`templates.harbor` reference that does not resolve is a hard error.

### Testcontainers repos

Repos whose tests need the Docker daemon (Testcontainers, or tests that shell
out to `docker`) require socket access that `task.toml`'s `[environment]` table
can't express. The skill detects this and applies a
`environment/docker-compose.yaml` overlay granting `privileged` + socket mount,
and adds the Testcontainers env vars. **Trade-off:** compose overlays only work
on Docker environments — cloud sandbox providers won't run such tasks — and the
mounted socket exposes the host daemon. Tag these tasks with a `testcontainers`
keyword. See
[`harbor/dpaia/spring-petclinic/`](https://github.com/dpaia/.dpaia_templates/tree/main/harbor/dpaia/spring-petclinic)
for a complete example.

## `.harbor/metadata.json` reference

`.harbor/metadata.json` is **data**, not a template — it takes precedence over
`.ee-bench/codegen/metadata.json` in the metadata fallback chain. It supplies
values the PR does not already carry and steers the export pipeline. Full
catalog: [`harbor/VARIABLES.md`](https://github.com/dpaia/.dpaia_templates/blob/main/harbor/VARIABLES.md).

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `language` | string | Programming language (`"java"`, `"kotlin"`, `"csharp"`, …). **Drives the output path** `_harbor_converted/<language>/…` — export errors if absent. |
| `expected.fail_to_pass` | string[] | Tests that must fail on the base commit and pass after the gold patch — the core signal. Fully-qualified class or `Class#method` names. |
| `expected.pass_to_pass` | string[] | Regression guard: tests that must stay green before and after. |
| `patch.source_patterns` | string[] | Globs forcing changed files into the **gold/source** patch (highest priority). Use for production files that look like tests (e.g. a `TestSupport.java` helper under `src/main`). |
| `patch.test_patterns` | string[] | Globs forcing changed files into the **test** patch. Use for fixtures/harnesses the built-in heuristic misses. |
| `templates.harbor` | string \| `false` | Select a named template (`"[<owner>/<repo>:]<path>"`), or `false` to opt out of harbor generation. |
| `jvm_version`, `build_system`, *custom* | any | Override a template's baked `\| default(...)` fallback. Reference in the template as `instance.<field>`. |

> **Patch splitting.** The export script splits your PR diff into a gold patch
> (`solution/patch.diff`) and a test patch (`tests/test_patch.diff`). Each
> changed file is classified by precedence: `source_patterns` → `test_patterns`
> → built-in test heuristic → otherwise source. `.ee-bench/` and `.harbor/`
> files are always excluded. An empty gold patch (no non-test source change) is
> a hard error — every datapoint must have production code for the agent to
> write. Override the split only when the heuristic misclassifies a file.

### Example — with patch overrides

```json
{
  "language": "java",
  "jvm_version": 24,
  "expected": {
    "fail_to_pass": [
      "com.procurement.vendors.api.VendorControllerVersioningTest"
    ],
    "pass_to_pass": []
  },
  "patch": {
    "source_patterns": ["src/main/**/TestSupport.java"],
    "test_patterns": ["src/it/**", "**/fixtures/**"]
  }
}
```

For shared field semantics (choosing `fail_to_pass` vs `pass_to_pass`,
class-level vs method-level selectors, Gradle multimodule names), see the
[EE-Bench guide's methodology section](contribution-guide.md#choosing-an-evaluation-methodology).

## Local eval deep-dive

The runner is a wrapper around `harbor jobs start`. Everything goes through
`skills/run-harbor-eval/scripts/harbor_eval.py`. Config precedence (later wins):

```
scripts/.env → scripts/.env.local → process env → --profile → CLI flags
```

Key points for the `dpaia` query flow:

- `--dpaia-query 'is:pr label:Spring repo:dpaia/saas-procurement'` resolves a board query to instance
  ids, exports the matching tasks into `~/.cache/harbor-jetbrains-eval/dpaia/`,
  and runs them. `--dpaia-eval-type` defaults to `codegen`.
- `--dpaia-instance-id ID_OR_GLOB` adds instances directly (the only way to
  reach `_harbor_manual` tasks). Provide at least one of query or instance ids.
- `-i` composes as an include filter over the resolved slice. `dpaia` refs
  cannot combine with `--dataset PATH`.
- A complete cache entry is reused without re-dispatching CI; `--force-download`
  forces a fresh export. `--dry-run` previews the dispatch/command without
  running.

Choose the agent with `--harness` and the model with `--model`:

```bash
./skills/run-harbor-eval/scripts/harbor_eval.py --detach \
  --harness codex --model openai/gpt-5.5 \
  --dpaia-instance-id dpaia__feature__service-245 \
  --job-name codex-run-$(date +%Y%m%d-%H%M%S)
```

Reusable experiment wiring (agent, model, Docker/env overlays, tasks) lives in
YAML **profiles** at `.harbor-jetbrains/profiles.yaml`. Full reference:
[`README_RUN_EVAL.md`](https://github.com/JetBrains/ide-eval-harbor/blob/main/README_RUN_EVAL.md)
and `skills/run-harbor-eval/SKILL.md`.

## Running the evaluation with an IDE and skills

To run the agent inside a JetBrains IDE via MCP, add `--ide <type>` (e.g.
`--ide idea`) plus an archive:

```bash
./skills/run-harbor-eval/scripts/harbor_eval.py --detach \
  --ide idea --ide-archive /path/to/ideaIU.tar.gz \
  --harness codex --model openai/gpt-5.5 \
  --dpaia-instance-id dpaia__feature__service-245 \
  --job-name codex-idea-$(date +%Y%m%d-%H%M%S)
```

Supported products: `idea`, `pycharm`, `intellij`, `goland`, `rider`,
`webstorm`, `phpstorm`, `clion`, `rubymine`.

> **MCP changes require rebuilding the IDE.** If you change the IDE's MCP
> configuration or the IDE plugin, you must rebuild the IDE archive (or point
> the profile at a source checkout with `ide.rebuild: true`). Runtime MCP
> knobs the wrapper exposes — `--mcp-allowed-tools`, `--mcp-invocation-mode`
> (`via-router` | `direct`) — do not need a rebuild.

**Skills** need no rebuild. Pass them per run, or configure them in a profile:

```bash
./skills/run-harbor-eval/scripts/harbor_eval.py --detach \
  --ide idea \
  --skill /abs/path/to/skill-one --skill /abs/path/to/skill-two \
  --dpaia-instance-id dpaia__feature__service-245 \
  --job-name codex-idea-skills-$(date +%Y%m%d-%H%M%S)
```

```yaml
# .harbor-jetbrains/profiles.yaml
profiles:
  idea-with-skills:
    ide: {product: idea}
    skills:
      - /abs/path/to/skill-one
      - /abs/path/to/skill-two
    system_prompt: "You must load and use the following skills: {skill_list}"
```

Keep the system prompt short — the eval should measure skill behavior, not a
hand-written instruction appendix. Full IDE MCP and skills reference:
[`README_RUN_EVAL.md` → JetBrains IDE MCP Runs / Skills](https://github.com/JetBrains/ide-eval-harbor/blob/main/README_RUN_EVAL.md#jetbrains-ide-mcp-runs).

## Comparing results with Harbor

**Reward files** (per trial) are the authoritative outcome:

```text
jobs/<job-name>/<trial-name>/verifier/reward.txt   # 1 = solved, 0 = not
jobs/<job-name>/<trial-name>/verifier/reward.json  # per-criterion detail
```

Quick checks:

```bash
jq '.stats' jobs/<job-name>/result.json
rg --files jobs/<job-name> | rg '/verifier/reward\.(txt|json)$'
```

**Viewer UI** — browse jobs and trials interactively:

```bash
uv run harbor view jobs --jobs --port 8091-8099
```

**Multi-job comparison CSV** — build a table across several jobs (reward,
duration, cost, token counts, tool-call breakdowns), one row per trial plus a
`TOTAL` row:

```bash
python docs/experiments/pycharm-mcp/build_pycharm_mcp_csv.py \
  --output comparison.csv \
  jobs/<job-name-1> jobs/<job-name-2>
```

The script keeps normally completed trials (no exception, reward present). It
works for any IDE product despite the `pycharm-mcp` path. See
[`README_RUN_EVAL.md` → Results / CSV Results / View Results](https://github.com/JetBrains/ide-eval-harbor/blob/main/README_RUN_EVAL.md#results)
and `skills/run-harbor-eval/inspecting-results.md`.

> **Budget exceptions:** if the verifier reward is `1.0` but the agent hit
> `error_max_budget_usd`, count it as solved with an operational budget
> exception — check both reward and exception status.

## Best practices for a good datapoint

- **The PR body is the task.** Write it as an agent-facing problem statement:
  what to achieve, not how. Put narrowing context in `hints_text` /
  `requirements` blocks rather than baking it into the problem statement.
- **Tests must actually gate the fix.** Your `fail_to_pass` tests must fail on
  the base commit and pass only with the gold patch. If a test passes at
  baseline, it proves nothing.
- **Prefer method-level `fail_to_pass`** when only some methods of a class fail
  at baseline. Class-level selectors flag a "baseline unexpected pass" when
  sibling methods already pass.
- **Add a `pass_to_pass` regression guard** for the most relevant existing
  tests so a solution that breaks nearby behavior is caught.
- **Keep the PR minimal and focused.** A tight gold patch (one coherent change)
  is easier to verify, reproduce, and evaluate than a sprawling one. The gold
  patch must contain real production code — an empty gold patch is a hard error.
- **Steer patch splitting only when needed.** Trust the built-in heuristic;
  add `source_patterns` / `test_patterns` only for genuinely misclassified
  files, and verify the split by exporting locally.
- **Mind Testcontainers.** Tasks needing the Docker socket run only on Docker
  environments and expose the host daemon. Tag them `testcontainers`; prefer
  non-Testcontainers datapoints when the same behavior can be tested without a
  live container.
- **Verify locally before asking for review.** Run the datapoint through
  `ide-eval-harbor` (steps 6–8) so you know the oracle reaches reward 1 before
  the board pipeline runs it.

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Verification stays **Invalid** | Oracle run did not reach reward 1 | Read the PR comment and linked workflow run; confirm `fail_to_pass` tests fail at baseline and pass with the gold patch. |
| "Template not found" hard error | `templates.harbor` names a path that doesn't resolve | Fix the reference, or remove it to use the default `harbor/dpaia/<repo>/`. |
| Export fails: empty gold patch | The PR diff has no non-test production change | Ensure the PR includes the production code the agent must write. |
| Files misrouted between gold/test patch | Non-standard test/source locations | Set `patch.test_patterns` / `patch.source_patterns` in `.harbor/metadata.json`. |
| `--dpaia-query` fails to resolve | `gh` not authenticated for board/Actions/workflow-dispatch on `dpaia/infrastructure` | Re-auth `gh` with the required scopes; use `--dry-run` to preview the dispatch. |
| Status reset to "In progress" | New commits pushed to the PR | Expected — the pipeline invalidates prior verification when code changes. |
| Docker build / IDE archive errors | Missing/stale image or IDE archive | See [`README_RUN_EVAL.md` → Troubleshooting](https://github.com/JetBrains/ide-eval-harbor/blob/main/README_RUN_EVAL.md#troubleshooting). |
