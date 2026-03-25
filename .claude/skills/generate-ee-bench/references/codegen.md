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
    └── scripts/                 # Optional: helper scripts used by run.sh
        └── ...
```

Only `metadata.json`, `Dockerfile`, and `run.sh` are required. The `eval/scripts/` directory is optional — `run.sh` can use helper scripts (e.g., `parser.py`, `emitter.py`) but can also be fully self-contained. The templates below include `parser.py` and `emitter.py` as reusable helpers for parsing test results and emitting the JSON output, but these are a convenience, not a requirement.

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

Generate with detected values. Use placeholders for test names:

```json
{
  "version": "1.0",
  "benchmark_type": "codegen",
  "language": "<detected>",
  "<language-specific fields>": "<detected values>",
  "expected": {
    "fail_to_pass": [
      "TODO: Add fully qualified test names that should fail before fix and pass after"
    ],
    "pass_to_pass": [
      "TODO: Add fully qualified test names that should always pass"
    ]
  },
  "environment": {
    "project_root": "<detected default>"
  }
}
```

**Note:** `expected.fail_to_pass` and `expected.pass_to_pass` are consumed by `run.sh` at **template render time**. They are baked into the script as JSON literals via `{{ instance.expected.fail_to_pass | tojson }}` and `{{ instance.expected.pass_to_pass | tojson }}`, so the running container does not need access to `metadata.json`.

Language-specific fields to include:

| Language | Fields |
|----------|--------|
| C# | `dotnet_sdk`, `test_project`, `test_framework_flag`, `test_logger` |
| Python | `python_version` |
| Gradle | `jvm_version` |
| Maven | `jvm_version` |

### environment/Dockerfile

Generate a Dockerfile following these specifications. **All Dockerfiles must:**
- Use `{{ instance.owner }}`, `{{ instance.repo_name }}`, `{{ instance.base_commit }}`, `{{ instance.project_root }}` Jinja2 variables
- Install `git` and any tools needed by `run.sh` and its helper scripts (e.g., `python3` if using the parser/emitter helpers)
- Clone the repo and checkout base commit
- Pre-fetch/cache dependencies
- Include labels: `LABEL ee-bench.type="codegen"` and `LABEL ee-bench.version="1.0"`
- End with: `RUN rm -rf <project_root>/.ee-bench/ 2>/dev/null || true`

**C# Dockerfile:**
```dockerfile
FROM mcr.microsoft.com/dotnet/sdk:{{ instance.dotnet_sdk }}-noble

ENV DEBIAN_FRONTEND=noninteractive

RUN sed -i 's|http://archive.ubuntu.com/ubuntu/|http://eu-west-1.ec2.archive.ubuntu.com/ubuntu/|g' /etc/apt/sources.list.d/ubuntu.sources && \
    sed -i 's|http://security.ubuntu.com/ubuntu/|http://eu-west-1.ec2.archive.ubuntu.com/ubuntu/|g' /etc/apt/sources.list.d/ubuntu.sources && \
    apt-get update

RUN apt-get update && \
    apt-get install -y build-essential git curl wget sudo python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{{ instance.owner }}/{{ instance.repo_name }}.git /app
WORKDIR /app
RUN git checkout {{ instance.base_commit }}

RUN dotnet restore

LABEL ee-bench.type="codegen"
LABEL ee-bench.version="1.0"
RUN rm -rf /app/.ee-bench/ 2>/dev/null || true
```

If the project needs additional dotnet SDK versions (e.g., tests target multiple frameworks), add `dotnet-install.sh` lines.

**Python Dockerfile:**
```dockerfile
FROM python:{{ instance.python_version }}-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y build-essential git curl && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{{ instance.owner }}/{{ instance.repo_name }}.git /app
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

**Gradle Dockerfile:**
```dockerfile
FROM eclipse-temurin:{{ instance.jvm_version }}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y build-essential git curl wget python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{{ instance.owner }}/{{ instance.repo_name }}.git {{ instance.project_root }}
WORKDIR {{ instance.project_root }}
RUN git checkout {{ instance.base_commit }}

RUN chmod +x ./gradlew && \
    ./gradlew dependencies --no-daemon -q

LABEL ee-bench.type="codegen"
LABEL ee-bench.version="1.0"
RUN rm -rf {{ instance.project_root }}/.ee-bench/ 2>/dev/null || true
```

**Maven Dockerfile:**
```dockerfile
FROM eclipse-temurin:{{ instance.jvm_version }}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y build-essential git curl wget python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{{ instance.owner }}/{{ instance.repo_name }}.git {{ instance.project_root }}
WORKDIR {{ instance.project_root }}
RUN git checkout {{ instance.base_commit }}

RUN chmod +x ./mvnw && \
    ./mvnw dependency:go-offline -q

LABEL ee-bench.type="codegen"
LABEL ee-bench.version="1.0"
RUN rm -rf {{ instance.project_root }}/.ee-bench/ 2>/dev/null || true
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
- `baseline_tests` — no test_patch file or compilation failed
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

  python3 "$EVAL_DIR/scripts/parser.py" "$ARTIFACTS_DIR" > "/tmp/${label}_parser.json" 2>/dev/null || echo '{}' > "/tmp/${label}_parser.json"

  export ARTIFACTS_DIR="$orig_artifacts"
}

cd "$PROJECT_ROOT"

# --- Reset to base commit (only if EE_BENCH_RESET is set) ---
if [ -n "${EE_BENCH_RESET:-}" ]; then
  git reset --hard "{{ instance.base_commit }}" 2>/dev/null
  git clean -fdx 2>/dev/null
fi

# ============================================================
# Apply test patch (setup — not a criterion)
# ============================================================
HAS_TEST_PATCH="false"
if [ -f "$EVAL_DIR/test_patch.diff" ]; then
  git apply -v "$EVAL_DIR/test_patch.diff" 2>/dev/null || true
  HAS_TEST_PATCH="true"
fi

# ============================================================
# Criterion: compilation (initial build)
# ============================================================
COMPILE_START=$SECONDS
COMPILE_STATUS="pass"
<COMPILE_COMMAND> > /tmp/compile_stdout.log 2> /tmp/compile_stderr.log || {
  COMPILE_STATUS="fail"
}
COMPILE_DURATION=$(_elapsed $COMPILE_START)

# ============================================================
# Run baseline tests (only if test_patch exists)
# ============================================================
BASELINE_DURATION=0
if [ "$COMPILE_STATUS" = "pass" ] && [ "$HAS_TEST_PATCH" = "true" ]; then
  BASELINE_START=$SECONDS
  _run_tests baseline
  BASELINE_DURATION=$(_elapsed $BASELINE_START)
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
if [ "$COMPILE_STATUS" = "pass" ] && [ "$PATCH_STATUS" = "pass" ]; then
  <COMPILE_COMMAND> > /tmp/rebuild_stdout.log 2> /tmp/rebuild_stderr.log || {
    REBUILD_STATUS="fail"
    COMPILE_STATUS="fail"
  }
  if [ "$REBUILD_STATUS" != "fail" ]; then
    REBUILD_STATUS="pass"
  fi
fi

# ============================================================
# Run eval tests (only if compilation and patch OK)
# ============================================================
TEST_DURATION=0
if [ "$COMPILE_STATUS" = "pass" ] && [ "$PATCH_STATUS" = "pass" ]; then
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

python3 "$EVAL_DIR/scripts/emitter.py"
```

**Language-specific substitutions:**

| Language | `<default_project_root>` | `<COMPILE_COMMAND>` | `<TEST_COMMAND>` |
|----------|-------------------------|---------------------|------------------|
| C# | `/app` | `bash "$EVAL_DIR/scripts/install.sh"` | `dotnet test --no-build {{ instance.test_framework_flag }} "{{ instance.test_project }}" --logger "{{ instance.test_logger }}"` |
| Python | `/app` | `pip install -e .` | `python -m pytest --junitxml="$ARTIFACTS_DIR/results.xml" -v` |
| Gradle | `/repo` | `./gradlew classes testClasses --no-daemon -q` | `./gradlew test --no-daemon` |
| Maven | `/repo` | `./mvnw compile test-compile -q` | `./mvnw test -q` |

### eval/scripts/parser.py (optional helper)

The templates include a reusable parser that handles both JUnit XML and TRX formats. This is an optional helper script called by `run.sh` — not a required file. If the project uses a different test output format, `run.sh` can parse results directly or use a different helper.

Key design points:
- `parse_junit_xml()` and `parse_trx()` accept a pre-parsed `ET.Element` root (not a file path) -- `detect_and_parse()` parses the XML once and dispatches by root tag
- `aggregate()` uses a single-pass loop to collect names and count errors simultaneously
- Output schema has top-level `summary`, `passed_tests`, `failed_tests`, `skipped_tests`, `methods` (no top-level `total`/`passed`/`failed`)

```python
#!/usr/bin/env python3
"""Parse test result logs (JUnit XML or TRX) into EE-bench JSON."""
import json
import os
import sys
import xml.etree.ElementTree as ET

MAX_STACKTRACE = 4096


def _truncate(text: str, limit: int = MAX_STACKTRACE) -> str:
    if text and len(text) > limit:
        return text[:limit] + "\n... [truncated]"
    return text


def parse_junit_xml(root: ET.Element) -> list[dict]:
    """Parse JUnit XML format (<testsuites><testsuite><testcase>)."""
    methods = []

    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = root.findall("testsuite")
    else:
        suites = root.findall(".//testsuite")

    for suite in suites:
        for tc in suite.findall("testcase"):
            name = tc.get("name", "unknown")
            classname = tc.get("classname", "")
            if classname and not name.startswith(classname):
                full_name = f"{classname}.{name}"
            else:
                full_name = name

            duration = 0.0
            try:
                duration = float(tc.get("time", "0"))
            except (ValueError, TypeError):
                pass

            entry = {"name": full_name, "duration_seconds": duration}

            failure = tc.find("failure")
            error = tc.find("error")
            skipped = tc.find("skipped")

            if failure is not None:
                entry["status"] = "failed"
                entry["type"] = "assertion"
                entry["message"] = failure.get("message", "")
                entry["stacktrace"] = _truncate(failure.text or "")
            elif error is not None:
                entry["status"] = "failed"
                entry["type"] = "error"
                entry["message"] = error.get("message", "")
                entry["stacktrace"] = _truncate(error.text or "")
            elif skipped is not None:
                entry["status"] = "skipped"
                msg = skipped.get("message", "") or (skipped.text or "")
                if msg:
                    entry["message"] = msg
            else:
                entry["status"] = "passed"

            methods.append(entry)
    return methods


def parse_trx(root: ET.Element) -> list[dict]:
    """Parse Visual Studio TRX format."""
    ns = {"t": "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"}
    methods = []

    for result in root.findall(".//t:UnitTestResult", ns):
        name = result.get("testName", "unknown")
        outcome = result.get("outcome", "").lower()

        duration = 0.0
        dur_str = result.get("duration", "")
        if dur_str:
            try:
                parts = dur_str.split(":")
                if len(parts) == 3:
                    h, m = int(parts[0]), int(parts[1])
                    s = float(parts[2])
                    duration = h * 3600 + m * 60 + s
            except (ValueError, IndexError):
                pass

        entry = {"name": name, "duration_seconds": duration}

        if outcome == "passed":
            entry["status"] = "passed"
        elif outcome in ("failed", "error"):
            entry["status"] = "failed"
            entry["type"] = "error" if outcome == "error" else "assertion"
            error_info = result.find("t:Output/t:ErrorInfo", ns)
            if error_info is not None:
                msg_el = error_info.find("t:Message", ns)
                st_el = error_info.find("t:StackTrace", ns)
                if msg_el is not None and msg_el.text:
                    entry["message"] = msg_el.text
                if st_el is not None and st_el.text:
                    entry["stacktrace"] = _truncate(st_el.text)
        elif outcome in ("notexecuted", "inconclusive"):
            entry["status"] = "skipped"
        else:
            entry["status"] = "failed"

        methods.append(entry)
    return methods


def detect_and_parse(artifacts_dir: str) -> list[dict]:
    """Scan artifacts dir for XML/TRX files and parse them."""
    methods = []
    for fname in sorted(os.listdir(artifacts_dir)):
        fpath = os.path.join(artifacts_dir, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            tree = ET.parse(fpath)
            root = tree.getroot()
        except ET.ParseError:
            continue

        ns_tag = root.tag
        if "TestRun" in ns_tag or "VisualStudio" in ns_tag:
            methods.extend(parse_trx(root))
        elif root.tag in ("testsuites", "testsuite"):
            methods.extend(parse_junit_xml(root))
        else:
            if root.findall(".//testcase"):
                methods.extend(parse_junit_xml(root))

    return methods


def aggregate(methods: list[dict]) -> dict:
    """Build method-level aggregation and summary from parsed results."""
    passed_names = []
    failed_names = []
    skipped_names = []
    total_duration = 0.0
    n_errors = 0

    for m in methods:
        total_duration += m.get("duration_seconds", 0.0)
        status = m["status"]
        if status == "passed":
            passed_names.append(m["name"])
        elif status == "failed":
            failed_names.append(m["name"])
            if m.get("type") == "error":
                n_errors += 1
        elif status == "skipped":
            skipped_names.append(m["name"])

    n_passed = len(passed_names)
    n_failed = len(failed_names)
    n_skipped = len(skipped_names)

    return {
        "summary": {
            "total": len(methods),
            "passed": n_passed,
            "failed": n_failed - n_errors,
            "errors": n_errors,
            "skipped": n_skipped,
            "duration_seconds": round(total_duration, 3),
        },
        "passed_tests": [{"name": n} for n in sorted(set(passed_names))],
        "failed_tests": [{"name": n} for n in sorted(set(failed_names))],
        "skipped_tests": [{"name": n} for n in sorted(set(skipped_names))],
        "methods": methods,
    }


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <artifacts_dir>", file=sys.stderr)
        sys.exit(1)

    artifacts_dir = sys.argv[1]
    methods = detect_and_parse(artifacts_dir)
    result = aggregate(methods)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
```

### eval/scripts/emitter.py (optional helper)

The emitter is a separate, language-agnostic Python script that reads environment variables (set by `run.sh`) and parser JSON files from `/tmp`, then prints the final EE-bench JSON v2.0 to stdout. This is an optional helper — `run.sh` could emit the JSON directly if preferred.

Key features:
- **`_prefix(name)`** strips parameterized suffixes: `Foo.Bar(x: 1)` becomes `Foo.Bar`
- **`_test_in(name, name_set)`** matches by exact name first, then by prefix (handles parameterized test methods)
- **`_evaluate_criterion()`** is a shared helper for both `fail_to_pass` and `pass_to_pass` criteria -- it checks eval pass status and baseline consistency in one call
- Reads `HAS_TEST_PATCH` env var to decide whether baseline checks apply
- Empty `fail_to_pass` list results in `"fail"` status; empty `pass_to_pass` results in `"skipped"`

## Step 5: Post-Generation

After generating all files, report to the user:

1. **What was generated**: List all created files with their paths
2. **What to fill in manually**:
   - `expected.fail_to_pass` in `metadata.json` — fully qualified names of tests that should fail before the fix and pass after
   - `expected.pass_to_pass` in `metadata.json` — fully qualified names of tests that should always pass
3. **How to verify locally**: Point user to the Local Testing section of the contribution guide — render templates, build Docker image, run tests, check JSON output
4. **Dockerfile customization**: If the project has unusual dependencies, the user may need to add extra `RUN` commands to the Dockerfile