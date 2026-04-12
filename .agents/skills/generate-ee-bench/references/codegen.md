# Codegen Evaluation Type

Generate `.ee-bench/codegen/` configuration that builds a Docker image, runs tests, and outputs results in EE-bench JSON v2.0 schema.

## Output Structure

```
.ee-bench/codegen/
├── metadata.json                # Required: datapoint configuration
├── environment/
│   └── Dockerfile               # Required: builds the test environment
└── eval/
    ├── run.sh                   # Required: evaluation entry point
    └── scripts/                 # Shared utility scripts
        ├── ee_bench_eval.py     # Language-independent emitter (from templates/shared/)
        └── ee_bench_parser_*.py # Language-specific parser (from templates/shared/)
```

`metadata.json`, `Dockerfile`, and `run.sh` are required. The `eval/scripts/` directory contains shared utility scripts that are copied from `guides/templates/shared/scripts/` in the infrastructure repository:

- **`ee_bench_eval.py`** — language-independent emitter that builds schema v2.0 JSON output with all 6 criteria (compilation, baseline_tests, patch_applied, tests, fail_to_pass, pass_to_pass). Used by all languages.
- **`ee_bench_parser_junit.py`** — JUnit XML parser for Java/Maven/Gradle/Python projects.
- **`ee_bench_parser_trx.py`** — TRX parser for C#/.NET projects.

**The skill must copy these shared scripts** into `.ee-bench/codegen/eval/scripts/` when generating configuration. Select the parser based on the detected build system.

## Step 1: Detect Build System

Check for file markers in this order (first match wins):

| Priority | Marker files | Build system |
|----------|-------------|--------------|
| 1 | `*.csproj` or `*.sln` | C# (dotnet) |
| 2 | `pom.xml` | Maven |
| 3 | `build.gradle` or `build.gradle.kts` | Gradle |
| 4 | `pyproject.toml` or `setup.py` or `setup.cfg` | Python |
| 5 | `requirements.txt` | Python (fallback) |

If no markers found, ask the user to specify.

## Step 2: Analyze Project

Extract language-specific values needed for template generation.

### C# (dotnet)

1. **Find test project**: Glob for `**/*Test*.csproj` or `**/*Tests*.csproj`
   - If multiple found, ask user which one to use
   - Store relative path as `test_project`
2. **Target framework**: Read the test `.csproj`, find `<TargetFramework>` element
   - Map to `test_framework_flag`: e.g. `net8.0` → `--framework net8.0`
   - Map to `dotnet_sdk`: `net8.0` → `"8.0"`, `net9.0` → `"9.0"`, `net6.0` → `"6.0"`
3. **Logger**: `trx;LogFileName=results.trx`
4. **Default project_root**: `/app`

### Python

1. **Python version**: Parse `pyproject.toml` for `requires-python` or check classifiers for `Programming Language :: Python :: X.Y`
   - Default: `"3.11"`
2. **Test framework**: Check if `pytest` appears in dependencies (pyproject.toml, requirements*.txt)
   - Default: pytest
3. **Default project_root**: `/app`

### Gradle

1. **JVM version**: Check (in order):
   - `gradle.properties` for `jvmTarget` or `org.gradle.java.home`
   - `build.gradle`/`build.gradle.kts` for `sourceCompatibility`, `java.toolchain.languageVersion`
   - Default: `"21"`
2. **Wrapper**: Verify `gradlew` exists in repo root
3. **Default project_root**: `/repo`

### Maven

1. **JVM version**: Parse `pom.xml` for:
   - `<maven.compiler.source>` or `<maven.compiler.release>` in `<properties>`
   - `<java.version>` property
   - Default: `"21"`
2. **Wrapper**: Check if `mvnw` exists. If not, use `mvn` and note this to user
3. **Default project_root**: `/repo`

### Detect Docker-in-Docker Requirements

Scan project dependencies for libraries that start Docker containers during tests:

| Build system | Where to scan | Match pattern |
|-------------|---------------|---------------|
| Maven | `pom.xml` | `<groupId>org.testcontainers</groupId>` |
| Gradle | `build.gradle(.kts)` | `testcontainers` in dependency declarations |
| Python | `pyproject.toml`, `requirements*.txt` | `testcontainers` package name |
| C# | `*.csproj` | `Testcontainers` in `<PackageReference>` |

If detected, set `uses_testcontainers = true`. This affects Step 4:
1. **Dockerfile**: Add Docker CLI installation block after base packages
2. **metadata.json**: Add `environment.docker.run_params` with Docker-in-Docker config

## Step 3: Template Variables Reference

All files in `.ee-bench/codegen/` are rendered as **Jinja2 templates** before use. Use these variables in the generated Dockerfile and run.sh.

### Built-in Variables (always available at render time)

| Variable | Source | Description |
|----------|--------|-------------|
| `{{ instance.repo_url }}` | PR data | Repository clone URL |
| `{{ instance.base_commit }}` | PR data | Base commit SHA |
| `{{ instance.head_commit }}` | PR data | Head commit SHA |
| `{{ instance.owner }}` | Computed | Repository owner (e.g., `dpaia`) |
| `{{ instance.repo_name }}` | Computed | Repository name (e.g., `moq`) |
| `{{ instance.repo }}` | Computed | Full `owner/repo_name` |
| `{{ instance.instance_id }}` | PR data or metadata | Datapoint identifier |
| `{{ instance.project_root }}` | metadata or `/repo` | Working directory in container |

### Custom Variables from metadata.json

All top-level scalar fields from `metadata.json` are merged into the template context as `{{ instance.<field> }}`:

- `"python_version": "3.11"` → `{{ instance.python_version }}`
- `"jvm_version": "21"` → `{{ instance.jvm_version }}`
- `"dotnet_sdk": "8.0"` → `{{ instance.dotnet_sdk }}`
- `"test_project": "tests/Foo.Tests/Foo.Tests.csproj"` → `{{ instance.test_project }}`
- `"test_framework_flag": "--framework net8.0"` → `{{ instance.test_framework_flag }}`
- `"test_logger": "trx;LogFileName=results.trx"` → `{{ instance.test_logger }}`

### Rendering Rules

- Files without `{{` markers pass through unchanged
- `tojson` filter available for JSON serialization: `{{ instance.expected | tojson }}`
- `{{ instance.expected.fail_to_pass | tojson }}` and `{{ instance.expected.pass_to_pass | tojson }}` render JSON arrays of test names (baked into run.sh)
- Built-in fields take precedence — a metadata field will not override a built-in field of the same name

## Step 4: Generate Files

### metadata.json

Generate with detected values. Leave `expected` arrays empty — they are filled in later per datapoint, not at generation time:

```json
{
  "version": "1.0",
  "benchmark_type": "codegen",
  "language": "<detected>",
  "<language-specific fields>": "<detected values>",
  "expected": {
    "fail_to_pass": [],
    "pass_to_pass": []
  },
  "environment": {
    "project_root": "<detected default>"
  }
}
```

**Note:** `expected.fail_to_pass` and `expected.pass_to_pass` are consumed by `run.sh` at **template render time**. They are baked into the script as JSON literals via `{{ instance.expected.fail_to_pass | tojson }}` and `{{ instance.expected.pass_to_pass | tojson }}`, so the running container does not need access to `metadata.json`. These lists are populated per datapoint during the export pipeline — leave them empty when generating the config.

**Test name formats:** Expected test names support three formats:
- **Dot-separated** (default): `com.example.FooTest.testMethod`
- **Hash delimiter**: `com.example.FooTest#testMethod` — `#` separates class from method
- **Module prefix**: `my-module:com.example.FooTest#testMethod` — module before `:` is stripped for matching (JUnit XML does not include module names)
- **Class-level**: `com.example.FooTest` or `my-module:com.example.FooTest` — matches all methods in the class

Language-specific fields to include:

| Language | Fields |
|----------|--------|
| C# | `dotnet_sdk`, `test_project`, `test_framework_flag`, `test_logger` |
| Python | `python_version` |
| Gradle | `jvm_version` |
| Maven | `jvm_version` |

**If `uses_testcontainers` is true**, add to `environment`:

```json
"docker": {
  "run_params": {
    "privileged": true,
    "network": "host",
    "volumes": ["/var/run/docker.sock:/var/run/docker.sock"],
    "environment": {
      "TESTCONTAINERS_RYUK_DISABLED": "true",
      "TESTCONTAINERS_CHECKS_DISABLE": "true",
      "DOCKER_HOST": "unix:///var/run/docker.sock",
      "TESTCONTAINERS_HOST_OVERRIDE": "host.docker.internal"
    }
  }
}
```

### environment/Dockerfile

**If `uses_testcontainers` is true**, all Dockerfile templates below should replace their `apt-get install` RUN with an extended version that also installs Docker CLI:

```dockerfile
RUN apt-get update && \
    apt-get install -y build-essential git curl wget python3 python3-pip ca-certificates gnupg && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    chmod a+r /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list && \
    apt-get update && \
    apt-get install -y docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*
```

Generate a Dockerfile following these specifications. **All Dockerfiles must:**
- **Hardcode** the repository owner, repository name, base image version (with language version), and project root with actual detected values — do NOT use Jinja2 variables for these
- Use `{{ instance.base_commit }}` as the only Jinja2 template variable (it changes per datapoint)
- Install `git` and any tools needed by `run.sh` and its helper scripts (e.g., `python3` if using the parser/emitter helpers)
- Clone the repo and checkout base commit
- Pre-fetch/cache dependencies
- Include labels: `LABEL ee-bench.type="codegen"` and `LABEL ee-bench.version="1.0"`
- End with: `RUN rm -rf <project_root>/.ee-bench/ 2>/dev/null || true`

**C# Dockerfile** (replace `<detected_dotnet_sdk>`, `<detected_owner>`, `<detected_repo>` with actual values):
```dockerfile
FROM mcr.microsoft.com/dotnet/sdk:<detected_dotnet_sdk>-noble

ENV DEBIAN_FRONTEND=noninteractive

RUN sed -i 's|http://archive.ubuntu.com/ubuntu/|http://eu-west-1.ec2.archive.ubuntu.com/ubuntu/|g' /etc/apt/sources.list.d/ubuntu.sources && \
    sed -i 's|http://security.ubuntu.com/ubuntu/|http://eu-west-1.ec2.archive.ubuntu.com/ubuntu/|g' /etc/apt/sources.list.d/ubuntu.sources && \
    apt-get update

RUN apt-get update && \
    apt-get install -y build-essential git curl wget sudo python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/<detected_owner>/<detected_repo>.git /app
WORKDIR /app
RUN git checkout {{ instance.base_commit }}

RUN dotnet restore

LABEL ee-bench.type="codegen"
LABEL ee-bench.version="1.0"
RUN rm -rf /app/.ee-bench/ 2>/dev/null || true
```

If the project needs additional dotnet SDK versions (e.g., tests target multiple frameworks), add `dotnet-install.sh` lines.

**Python Dockerfile** (replace `<detected_python_version>`, `<detected_owner>`, `<detected_repo>` with actual values):
```dockerfile
FROM python:<detected_python_version>-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y build-essential git curl && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/<detected_owner>/<detected_repo>.git /app
WORKDIR /app
RUN git checkout {{ instance.base_commit }}

RUN pip install --no-cache-dir -e ".[dev,test]" 2>/dev/null || \
    pip install --no-cache-dir -e ".[test]" 2>/dev/null || \
    pip install --no-cache-dir -e . 2>/dev/null || true
RUN pip install --no-cache-dir -r requirements-dev.txt 2>/dev/null || \
    pip install --no-cache-dir -r requirements.txt 2>/dev/null || true
RUN pip install --no-cache-dir pytest

LABEL ee-bench.type="codegen"
LABEL ee-bench.version="1.0"
RUN rm -rf /app/.ee-bench/ 2>/dev/null || true
```

**Gradle Dockerfile** (replace `<detected_jvm_version>`, `<detected_owner>`, `<detected_repo>` with actual values):
```dockerfile
FROM eclipse-temurin:<detected_jvm_version>

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y build-essential git curl wget python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/<detected_owner>/<detected_repo>.git /repo
WORKDIR /repo
RUN git checkout {{ instance.base_commit }}

RUN chmod +x ./gradlew && \
    ./gradlew dependencies --no-daemon -q

LABEL ee-bench.type="codegen"
LABEL ee-bench.version="1.0"
RUN rm -rf /repo/.ee-bench/ 2>/dev/null || true
```

**Maven Dockerfile** (replace `<detected_jvm_version>`, `<detected_owner>`, `<detected_repo>` with actual values):
```dockerfile
FROM eclipse-temurin:<detected_jvm_version>

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y build-essential git curl wget python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/<detected_owner>/<detected_repo>.git /repo
WORKDIR /repo
RUN git checkout {{ instance.base_commit }}

RUN chmod +x ./mvnw && \
    ./mvnw dependency:go-offline -q

LABEL ee-bench.type="codegen"
LABEL ee-bench.version="1.0"
RUN rm -rf /repo/.ee-bench/ 2>/dev/null || true
```

### eval/run.sh

All run.sh scripts follow the same 6-criterion structure. Only the compile and test commands differ.

**Evaluation criteria:**

| Criterion | Description | Status values |
|-----------|-------------|---------------|
| `compilation` | Build via install.sh | `pass`, `fail` |
| `baseline_tests` | Test run before submission (with test_patch, no submission) | `pass`, `fail`, `skipped` |
| `patch_applied` | Apply submission patch | `pass`, `fail`, `skipped` |
| `tests` | Test run after submission | `pass`, `fail`, `skipped` |
| `fail_to_pass` | Expected-failing tests failed in baseline, pass after submission | `pass`, `fail`, `skipped` |
| `pass_to_pass` | Expected-passing tests passed in baseline, still pass after submission | `pass`, `fail`, `skipped` |

**When criteria are skipped:**

- `patch_applied` — no submission patch provided
- `baseline_tests` — compilation failed
- `tests` — compilation or patch application failed
- `fail_to_pass` — expected list empty or upstream criteria failed
- `pass_to_pass` — expected list empty or upstream criteria failed

**Common structure (all languages):**

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${EE_BENCH_PROJECT_ROOT:-<default_project_root>}"
EVAL_DIR="/ee-bench/eval"
SUBMISSION_DIR="/ee-bench/submission"
export ARTIFACTS_DIR="/tmp/test-results"
mkdir -p "$ARTIFACTS_DIR"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
OVERALL_START=$SECONDS

_elapsed() { echo $(( SECONDS - ${1:-$OVERALL_START} )); }

# --- _run_tests: run tests with isolated ARTIFACTS_DIR ---
# Usage: _run_tests <label>
# Writes: /tmp/<label>_stdout.log, /tmp/<label>_stderr.log, /tmp/<label>_parser.json
_run_tests() {
  local label="$1"
  local orig_artifacts="$ARTIFACTS_DIR"
  export ARTIFACTS_DIR="$orig_artifacts/$label"
  mkdir -p "$ARTIFACTS_DIR"

  set +e
  <TEST_COMMAND> > "/tmp/${label}_stdout.log" 2> "/tmp/${label}_stderr.log"
  set -e

  # Copy test reports to ARTIFACTS_DIR for parser (use find for multi-module support)
  <COPY_REPORTS_COMMAND>

  python3 "$EVAL_DIR/scripts/<PARSER_SCRIPT>" "$ARTIFACTS_DIR" > "/tmp/${label}_parser.json" 2>/dev/null || echo '{}' > "/tmp/${label}_parser.json"

  export ARTIFACTS_DIR="$orig_artifacts"
}

cd "$PROJECT_ROOT"

# --- Reset to base commit (only if EE_BENCH_RESET is set) ---
if [ -n "${EE_BENCH_RESET:-}" ]; then
  git reset --hard "{{ instance.base_commit }}" 2>/dev/null
  git clean -fdx 2>/dev/null
fi

# ============================================================
# Criterion: compilation (clean base, before test_patch)
# ============================================================
COMPILE_START=$SECONDS
COMPILE_STATUS="pass"
<COMPILE_COMMAND> > /tmp/compile_stdout.log 2> /tmp/compile_stderr.log || {
  COMPILE_STATUS="fail"
}
COMPILE_DURATION=$(_elapsed $COMPILE_START)

# ============================================================
# Run baseline tests (clean base, before test_patch)
# Establishes pass_to_pass baseline and fail_to_pass baseline.
# ============================================================
HAS_TEST_PATCH="false"
if [ -f "$EVAL_DIR/test_patch.diff" ]; then
  HAS_TEST_PATCH="true"
fi

BASELINE_DURATION=0
if [ "$COMPILE_STATUS" = "pass" ]; then
  BASELINE_START=$SECONDS
  _run_tests baseline
  BASELINE_DURATION=$(_elapsed $BASELINE_START)
fi

# ============================================================
# Apply test patch (after baseline, before gold patch)
# ============================================================
if [ "$HAS_TEST_PATCH" = "true" ]; then
  git apply -v "$EVAL_DIR/test_patch.diff" 2>/dev/null || true
fi

# ============================================================
# Criterion: patch_applied (submission patch)
# ============================================================
PATCH_START=$SECONDS
PATCH_STATUS="pass"
PATCH_OUTPUT=""
if [ -f "$SUBMISSION_DIR/patch.diff" ]; then
  PATCH_OUTPUT=$(git apply -v "$SUBMISSION_DIR/patch.diff" 2>&1) || {
    PATCH_STATUS="fail"
    echo "WARN: git apply failed for submission patch" >&2
  }
else
  PATCH_STATUS="skipped"
fi
PATCH_DURATION=$(_elapsed $PATCH_START)

# ============================================================
# Rebuild after submission patch
# ============================================================
REBUILD_STATUS="skipped"
if [ "$PATCH_STATUS" = "pass" ]; then
  <COMPILE_COMMAND> > /tmp/rebuild_stdout.log 2> /tmp/rebuild_stderr.log || {
    REBUILD_STATUS="fail"
  }
  if [ "$REBUILD_STATUS" != "fail" ]; then
    REBUILD_STATUS="pass"
    COMPILE_STATUS="pass"
  fi
fi

# ============================================================
# Run eval tests (only if rebuild/compilation OK and patch not failed)
# ============================================================
TEST_DURATION=0
if [ "$REBUILD_STATUS" = "pass" ] || ([ "$COMPILE_STATUS" = "pass" ] && [ "$PATCH_STATUS" != "fail" ]); then
  TEST_START=$SECONDS
  _run_tests eval
  TEST_DURATION=$(_elapsed $TEST_START)
fi

OVERALL_DURATION=$(_elapsed $OVERALL_START)

# --- Write temp files for safe passing to Python emitter ---
echo "$PATCH_OUTPUT" > /tmp/_patch_output.txt
cat /tmp/compile_stdout.log /tmp/compile_stderr.log > /tmp/_compile_output.txt 2>/dev/null || true

# --- Write expected test lists to file (avoids shell quoting issues) ---
cat > /tmp/_expected.json << 'EXPECTED_EOF'
{"fail_to_pass": {{ instance.expected.fail_to_pass | tojson }}, "pass_to_pass": {{ instance.expected.pass_to_pass | tojson }}}
EXPECTED_EOF

# ============================================================
# Emit EE-bench JSON v2.0 (6 criteria)
# ============================================================
export PATCH_STATUS PATCH_DURATION COMPILE_STATUS COMPILE_DURATION
export TEST_DURATION BASELINE_DURATION OVERALL_DURATION TIMESTAMP
export HAS_TEST_PATCH

python3 "$EVAL_DIR/scripts/ee_bench_eval.py"
```

**Language-specific substitutions:**

| Language | `<default_project_root>` | `<COMPILE_COMMAND>` | `<TEST_COMMAND>` | `<COPY_REPORTS_COMMAND>` | `<PARSER_SCRIPT>` |
|----------|-------------------------|---------------------|------------------|--------------------------|-------------------|
| C# | `/app` | `bash "$EVAL_DIR/scripts/install.sh"` | `dotnet test --no-build {{ instance.test_framework_flag }} "{{ instance.test_project }}" --logger "{{ instance.test_logger }}"` | *(empty — dotnet writes to ARTIFACTS_DIR via logger)* | `ee_bench_parser_trx.py` |
| Python | `/app` | `pip install -e .` | `python -m pytest --junitxml="$ARTIFACTS_DIR/results.xml" -v` | *(empty — pytest writes to ARTIFACTS_DIR via --junitxml)* | `ee_bench_parser_junit.py` |
| Gradle | `/repo` | `./gradlew classes testClasses --no-daemon -q` | `./gradlew test --no-daemon --continue` | `find "$PROJECT_ROOT" -path "*/build/test-results/test/*.xml" -exec cp {} "$ARTIFACTS_DIR/" \; 2>/dev/null \|\| true` | `ee_bench_parser_junit.py` |
| Maven | `/repo` | `./mvnw compile test-compile -q` | `./mvnw test -q` | `find "$PROJECT_ROOT" -path "*/target/surefire-reports/*.xml" -exec cp {} "$ARTIFACTS_DIR/" \; 2>/dev/null \|\| true` | `ee_bench_parser_junit.py` |

### eval/scripts/ — Shared utility scripts

The skill must copy shared utility scripts from `guides/templates/shared/scripts/` into `.ee-bench/codegen/eval/scripts/`. Select the correct parser based on detected build system:

| Build system | Scripts to copy |
|-------------|----------------|
| Maven, Gradle, Python | `ee_bench_eval.py` + `ee_bench_parser_junit.py` |
| C# | `ee_bench_eval.py` + `ee_bench_parser_trx.py` |

These shared scripts are the source of truth for evaluation logic. Do NOT generate parser or emitter scripts from scratch — always copy from the shared templates.

The parser scripts are located at `guides/templates/shared/scripts/` in the infrastructure repository. Copy the appropriate one for the detected build system. Do NOT generate parser code from scratch.

- **`ee_bench_parser_junit.py`**: Parses JUnit XML (`<testsuites>/<testsuite>/<testcase>`). For Maven, Gradle, Python (pytest).
- **`ee_bench_parser_trx.py`**: Parses Visual Studio TRX format. For C#/.NET.

Both parsers expose the same interface: `detect_and_parse(artifacts_dir)` → `list[dict]`, `aggregate(methods)` → `dict`, and `main()` CLI entry point.

Output schema:
```json
{
  "summary": {"total": N, "passed": N, "failed": N, "errors": N, "skipped": N, "duration_seconds": N},
  "passed_tests": [{"name": "..."}],
  "failed_tests": [{"name": "..."}],
  "skipped_tests": [{"name": "..."}],
  "methods": [{"name": "...", "status": "passed|failed|skipped", "duration_seconds": N}]
}
```

#### ee_bench_eval.py (language-independent emitter)

The emitter is located at `guides/templates/shared/scripts/ee_bench_eval.py`. Copy it to `.ee-bench/codegen/eval/scripts/ee_bench_eval.py`. Do NOT generate emitter code from scratch.

Key behavior:
- Reads env vars from `run.sh`: `COMPILE_STATUS`, `PATCH_STATUS`, `TEST_DURATION`, `HAS_TEST_PATCH`, etc.
- Reads temp files: `/tmp/_compile_output.txt`, `/tmp/_patch_output.txt`, `/tmp/_expected.json`, `/tmp/*_parser.json`
- Builds all 6 criteria (compilation, baseline_tests, patch_applied, tests, fail_to_pass, pass_to_pass)
- Handles wildcard expansion (`["*"]` means all discovered tests)
- Prints schema v2.0 JSON to stdout

## Step 5: Post-Generation

After generating all files, report to the user:

1. **What was generated**: List all created files with their paths
2. **What to fill in later** (per datapoint, not at generation time):
   - `expected.fail_to_pass` in `metadata.json` — fully qualified names of tests that should fail before the fix and pass after (left empty by default)
   - `expected.pass_to_pass` in `metadata.json` — fully qualified names of tests that should always pass (left empty by default)
3. **Dockerfile customization**: If the project has unusual dependencies, the user may need to add extra `RUN` commands to the Dockerfile

## Step 6: Verify and Fix

After reporting what was generated, automatically run verification if the `verify-ee-bench` skill is available:

1. **Invoke `/verify-ee-bench codegen`** — this renders templates in Docker, builds the image, discovers passing tests, and runs the full evaluation pipeline
2. **If verification fails**, analyze the error output and fix the generated files:
   - Dockerfile build failure → fix the Dockerfile (missing dependencies, wrong base image, etc.)
   - Test compilation failure → check compile commands match the project's build system
   - run.sh failure → fix script errors (wrong paths, missing tools, template rendering issues)
   - Output validation failure → fix JSON output format or criteria logic
   - Testcontainers errors → tests need Docker-in-Docker; add structured `environment.docker.run_params` to `metadata.json` with `privileged: true`, `network: "host"`, volume `/var/run/docker.sock:/var/run/docker.sock`, and env vars `TESTCONTAINERS_RYUK_DISABLED=true`, `TESTCONTAINERS_CHECKS_DISABLE=true`, `DOCKER_HOST=unix:///var/run/docker.sock`, `TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal`. Also install Docker CLI in the Dockerfile (see Step 2 detection and Step 4 Dockerfile templates)
3. **Re-run `/verify-ee-bench codegen`** after each fix until verification passes
4. If the `verify-ee-bench` skill is not installed, skip this step and point the user to the [Local Testing](../../guides/contribution-guide.md#local-testing) section of the contribution guide instead