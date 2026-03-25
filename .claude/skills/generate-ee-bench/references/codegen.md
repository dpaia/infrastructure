# Codegen Evaluation Type

Generate `.ee-bench/codegen/` configuration that builds a Docker image, runs tests, and outputs results in EE-bench JSON v2.0 schema.

## Output Structure

```
.ee-bench/codegen/
├── metadata.json
├── environment/
│   └── Dockerfile
└── eval/
    ├── run.sh
    └── scripts/
        └── parser.py
```

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
- `{{ instance.expected.FAIL_TO_PASS | tojson }}` and `{{ instance.expected.PASS_TO_PASS | tojson }}` render JSON arrays of test names (baked into run.sh)
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
    "FAIL_TO_PASS": [
      "TODO: Add fully qualified test names that should fail before fix and pass after"
    ],
    "PASS_TO_PASS": [
      "TODO: Add fully qualified test names that should always pass"
    ]
  },
  "environment": {
    "project_root": "<detected default>"
  }
}
```

**Note:** `expected.FAIL_TO_PASS` and `expected.PASS_TO_PASS` are consumed by `run.sh` at **template render time**. They are baked into the script as JSON literals via `{{ instance.expected.FAIL_TO_PASS | tojson }}` and `{{ instance.expected.PASS_TO_PASS | tojson }}`, so the running container does not need access to `metadata.json`.

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
- Install `git`, `python3`, `python3-pip` (needed for parser)
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
| `fail_to_pass` | FAIL_TO_PASS tests failed in baseline, pass after submission | `pass`, `fail`, `skipped` |
| `pass_to_pass` | PASS_TO_PASS tests passed in baseline, still pass after submission | `pass`, `fail`, `skipped` |

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
MAX_OUTPUT=51200

_elapsed() { echo $(( SECONDS - ${1:-$OVERALL_START} )); }

_capture_output() {
  local file="$1" limit="${2:-$MAX_OUTPUT}"
  if [ -f "$file" ]; then
    head -c "$limit" "$file"
  fi
}

# --- Helper: run tests in isolation (stash/unstash working tree) ---
_run_tests() {
  local label="$1" out_prefix="$2"
  local start=$SECONDS
  set +e
  <TEST_COMMAND> > "/tmp/${out_prefix}_stdout.log" 2> "/tmp/${out_prefix}_stderr.log"
  local exit_code=$?
  set -e
  local duration=$(( SECONDS - start ))
  <COPY_ARTIFACTS_IF_NEEDED>
  local parser_json
  parser_json=$(python3 "$EVAL_DIR/scripts/parser.py" "$ARTIFACTS_DIR" 2>/dev/null || echo '{}')
  rm -rf "$ARTIFACTS_DIR"/* 2>/dev/null || true
  echo "$duration" > "/tmp/${out_prefix}_duration.txt"
  echo "$parser_json" > "/tmp/${out_prefix}_parser.json"
  return $exit_code
}

cd "$PROJECT_ROOT"

# --- Reset to base commit (only if EE_BENCH_RESET is set) ---
if [ -n "${EE_BENCH_RESET:-}" ]; then
  git reset --hard "{{ instance.base_commit }}" 2>/dev/null
  git clean -fdx 2>/dev/null
fi

# ============================================================
# CRITERION 1: compilation
# ============================================================
COMPILE_START=$SECONDS
COMPILE_STATUS="pass"
<COMPILE_COMMAND> > /tmp/compile_stdout.log 2> /tmp/compile_stderr.log || {
  COMPILE_STATUS="fail"
}
COMPILE_DURATION=$(_elapsed $COMPILE_START)
COMPILE_OUTPUT=$(_capture_output /tmp/compile_stdout.log)
COMPILE_STDERR=$(_capture_output /tmp/compile_stderr.log)

# ============================================================
# CRITERION 2: baseline_tests (before submission, with test_patch)
# ============================================================
BASELINE_STATUS="skipped"
BASELINE_DURATION=0
BASELINE_OUTPUT=""
if [ "$COMPILE_STATUS" = "pass" ] && [ -f "$EVAL_DIR/test_patch.diff" ]; then
  git apply -v "$EVAL_DIR/test_patch.diff" 2>/dev/null || true
  _run_tests "baseline" "baseline" && BASELINE_STATUS="pass" || BASELINE_STATUS="pass"
  # baseline always "passes" — we just record what tests looked like before submission
  BASELINE_DURATION=$(cat /tmp/baseline_duration.txt 2>/dev/null || echo 0)
  BASELINE_OUTPUT=$(_capture_output /tmp/baseline_stdout.log)
fi

# ============================================================
# CRITERION 3: patch_applied
# ============================================================
PATCH_START=$SECONDS
PATCH_STATUS="skipped"
PATCH_OUTPUT=""
if [ -f "$SUBMISSION_DIR/patch.diff" ]; then
  PATCH_STATUS="pass"
  PATCH_OUTPUT=$(git apply -v "$SUBMISSION_DIR/patch.diff" 2>&1) || {
    PATCH_STATUS="fail"
    echo "WARN: git apply failed for submission patch" >&2
  }
fi
PATCH_DURATION=$(_elapsed $PATCH_START)

# --- Apply test patch if not already applied ---
if [ "$BASELINE_STATUS" = "skipped" ] && [ -f "$EVAL_DIR/test_patch.diff" ]; then
  git apply -v "$EVAL_DIR/test_patch.diff" 2>/dev/null || true
fi

# ============================================================
# CRITERION 4: tests (after submission)
# ============================================================
TEST_STATUS="skipped"
TEST_DURATION=0
TEST_OUTPUT=""
if [ "$COMPILE_STATUS" = "pass" ] && [ "$PATCH_STATUS" != "fail" ]; then
  _run_tests "eval" "test" && true
  TEST_DURATION=$(cat /tmp/test_duration.txt 2>/dev/null || echo 0)
  TEST_OUTPUT=$(_capture_output /tmp/test_stdout.log)
fi

OVERALL_DURATION=$(_elapsed $OVERALL_START)

# --- Write temp files for Python emitter ---
echo "$PATCH_OUTPUT" > /tmp/_patch_output.txt
echo "$COMPILE_OUTPUT" > /tmp/_compile_output.txt
printf '%s\n%s' "$COMPILE_STDERR" "" >> /tmp/_compile_output.txt
echo "$TEST_OUTPUT" > /tmp/_test_output.txt
echo "$BASELINE_OUTPUT" > /tmp/_baseline_output.txt

# ============================================================
# Emit EE-bench JSON v2.0 (6 criteria)
# ============================================================
# Expected test lists are baked in at template render time:
FAIL_TO_PASS_JSON='{{ instance.expected.FAIL_TO_PASS | tojson }}'
PASS_TO_PASS_JSON='{{ instance.expected.PASS_TO_PASS | tojson }}'

export PATCH_STATUS PATCH_DURATION COMPILE_STATUS COMPILE_DURATION
export TEST_STATUS TEST_DURATION BASELINE_STATUS BASELINE_DURATION
export OVERALL_DURATION TIMESTAMP

python3 -c "
import json, sys, os

def read_file(path, limit=51200):
    try:
        with open(path) as f:
            return f.read(limit)
    except Exception:
        return ''

def load_parser(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

compile_status = os.environ.get('COMPILE_STATUS', 'pass')
compile_duration = int(os.environ.get('COMPILE_DURATION', '0'))
baseline_status = os.environ.get('BASELINE_STATUS', 'skipped')
baseline_duration = int(os.environ.get('BASELINE_DURATION', '0'))
patch_status = os.environ.get('PATCH_STATUS', 'skipped')
patch_duration = int(os.environ.get('PATCH_DURATION', '0'))
test_status = os.environ.get('TEST_STATUS', 'skipped')
test_duration = int(os.environ.get('TEST_DURATION', '0'))
overall_duration = int(os.environ.get('OVERALL_DURATION', '0'))
timestamp = os.environ.get('TIMESTAMP', '')

compile_output = read_file('/tmp/_compile_output.txt')
baseline_output = read_file('/tmp/_baseline_output.txt')
patch_output = read_file('/tmp/_patch_output.txt')
test_output = read_file('/tmp/_test_output.txt')

baseline_parser = load_parser('/tmp/baseline_parser.json')
eval_parser = load_parser('/tmp/test_parser.json')

# Baked-in expected test lists
fail_to_pass = json.loads('$FAIL_TO_PASS_JSON')
pass_to_pass = json.loads('$PASS_TO_PASS_JSON')

# Extract passed/failed test name sets from parser results
def test_names(parser_data, status_key):
    return {t['name'] for t in parser_data.get(status_key, [])}

baseline_passed = test_names(baseline_parser, 'passed_tests')
baseline_failed = test_names(baseline_parser, 'failed_tests')
eval_passed = test_names(eval_parser, 'passed_tests')
eval_failed = test_names(eval_parser, 'failed_tests')

# Criterion 5: fail_to_pass
ftp_status = 'skipped'
if fail_to_pass and test_status != 'skipped' and baseline_status != 'skipped':
    ftp_ok = all(t in eval_passed and t in baseline_failed for t in fail_to_pass)
    ftp_status = 'pass' if ftp_ok else 'fail'

# Criterion 6: pass_to_pass
ptp_status = 'skipped'
if pass_to_pass and test_status != 'skipped' and baseline_status != 'skipped':
    ptp_ok = all(t in eval_passed and t in baseline_passed for t in pass_to_pass)
    ptp_status = 'pass' if ptp_ok else 'fail'

eval_summary = eval_parser.get('summary', {
    'total': 0, 'passed': 0, 'failed': 0, 'errors': 0, 'skipped': 0, 'duration_seconds': 0.0,
})

result = {
    'schema_version': '2.0',
    'status': 'success' if compile_status == 'pass' and patch_status != 'fail' and ftp_status == 'pass' else 'failure',
    'timestamp': timestamp,
    'duration_seconds': overall_duration,
    'criteria': [
        {
            'criterion': 'compilation',
            'status': compile_status,
            'duration_seconds': compile_duration,
            'output': compile_output[:51200],
        },
        {
            'criterion': 'baseline_tests',
            'status': baseline_status,
            'duration_seconds': baseline_duration,
            'output': baseline_output[:51200],
        },
        {
            'criterion': 'patch_applied',
            'status': patch_status,
            'duration_seconds': patch_duration,
            'output': patch_output[:51200],
        },
        {
            'criterion': 'tests',
            'status': test_status,
            'duration_seconds': test_duration,
            'output': test_output[:51200],
            'summary': eval_summary,
            'passed_tests': eval_parser.get('passed_tests', []),
            'failed_tests': eval_parser.get('failed_tests', []),
            'skipped_tests': eval_parser.get('skipped_tests', []),
            'methods': eval_parser.get('methods', []),
        },
        {
            'criterion': 'fail_to_pass',
            'status': ftp_status,
            'expected': fail_to_pass,
        },
        {
            'criterion': 'pass_to_pass',
            'status': ptp_status,
            'expected': pass_to_pass,
        },
    ],
}
print(json.dumps(result))
"
```

**Language-specific substitutions:**

| Language | `<default_project_root>` | `<COMPILE_COMMAND>` | `<TEST_COMMAND>` | `<COPY_ARTIFACTS_IF_NEEDED>` |
|----------|-------------------------|---------------------|------------------|------------------------------|
| C# | `/app` | `dotnet build {{ instance.test_project }}` | `dotnet test --no-build {{ instance.test_framework_flag }} "{{ instance.test_project }}" --logger "{{ instance.test_logger }}" --results-directory "$ARTIFACTS_DIR"` | *(none — results go directly to ARTIFACTS_DIR)* |
| Python | `/app` | `pip install -e .` | `python -m pytest --junitxml="$ARTIFACTS_DIR/results.xml" -v` | *(none — results go directly to ARTIFACTS_DIR)* |
| Gradle | `/repo` | `./gradlew classes testClasses --no-daemon -q` | `./gradlew test --no-daemon` | `find . -path "*/build/test-results/test/*.xml" -exec cp {} "$ARTIFACTS_DIR/" \; 2>/dev/null \|\| true` |
| Maven | `/repo` | `./mvnw compile test-compile -q` | `./mvnw test -q` | `find . -path "*/target/surefire-reports/*.xml" -exec cp {} "$ARTIFACTS_DIR/" \; 2>/dev/null \|\| true` |

### eval/scripts/parser.py

Generate the same parser for all languages. It handles both JUnit XML and TRX formats:

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


def parse_junit_xml(path: str) -> list[dict]:
    """Parse JUnit XML format (<testsuites><testsuite><testcase>)."""
    tree = ET.parse(path)
    root = tree.getroot()
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
            full_name = f"{classname}.{name}" if classname else name

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


def parse_trx(path: str) -> list[dict]:
    """Parse Visual Studio TRX format."""
    tree = ET.parse(path)
    root = tree.getroot()
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
            methods.extend(parse_trx(fpath))
        elif root.tag in ("testsuites", "testsuite"):
            methods.extend(parse_junit_xml(fpath))
        else:
            if root.findall(".//testcase"):
                methods.extend(parse_junit_xml(fpath))

    return methods


def aggregate(methods: list[dict]) -> dict:
    """Build class-level aggregation and summary from method-level results."""
    passed_classes = set()
    failed_classes = set()
    skipped_classes = set()
    total_duration = 0.0

    for m in methods:
        cls = m["name"].rsplit(".", 1)[0] if "." in m["name"] else m["name"]
        total_duration += m.get("duration_seconds", 0.0)
        if m["status"] == "passed":
            passed_classes.add(cls)
        elif m["status"] == "failed":
            failed_classes.add(cls)
        elif m["status"] == "skipped":
            skipped_classes.add(cls)

    passed_classes -= failed_classes
    passed_classes -= skipped_classes

    passed_tests = [{"name": c} for c in sorted(passed_classes)]
    failed_tests = [{"name": c} for c in sorted(failed_classes)]
    skipped_tests = [{"name": c} for c in sorted(skipped_classes)]

    n_passed = sum(1 for m in methods if m["status"] == "passed")
    n_failed = sum(1 for m in methods if m["status"] == "failed" and m.get("type") != "error")
    n_errors = sum(1 for m in methods if m["status"] == "failed" and m.get("type") == "error")
    n_skipped = sum(1 for m in methods if m["status"] == "skipped")

    summary = {
        "total": len(methods),
        "passed": n_passed,
        "failed": n_failed,
        "errors": n_errors,
        "skipped": n_skipped,
        "duration_seconds": round(total_duration, 3),
    }

    return {
        "total": len(methods),
        "passed": n_passed,
        "failed": n_failed + n_errors,
        "summary": summary,
        "passed_tests": passed_tests,
        "failed_tests": failed_tests,
        "skipped_tests": skipped_tests,
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

## Step 5: Post-Generation

After generating all files, report to the user:

1. **What was generated**: List all created files with their paths
2. **What to fill in manually**:
   - `expected.FAIL_TO_PASS` in `metadata.json` — fully qualified names of tests that should fail before the fix and pass after
   - `expected.PASS_TO_PASS` in `metadata.json` — fully qualified names of tests that should always pass
3. **How to verify locally**: Point user to the Local Testing section of the contribution guide — render templates, build Docker image, run tests, check JSON output
4. **Dockerfile customization**: If the project has unusual dependencies, the user may need to add extra `RUN` commands to the Dockerfile