#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${EE_BENCH_PROJECT_ROOT:-/app}"
EVAL_DIR="/ee-bench/eval"
SUBMISSION_DIR="/ee-bench/submission"
export ARTIFACTS_DIR="/tmp/test-results"
mkdir -p "$ARTIFACTS_DIR"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
OVERALL_START=$SECONDS
MAX_OUTPUT=51200  # 50K truncation limit

_elapsed() { echo $(( SECONDS - ${1:-$OVERALL_START} )); }

_capture_output() {
  local file="$1" limit="${2:-$MAX_OUTPUT}"
  if [ -f "$file" ]; then
    head -c "$limit" "$file"
  fi
}

# --- _run_tests: run pytest with isolated ARTIFACTS_DIR ---
_run_tests() {
  local label="$1"
  local orig_artifacts="$ARTIFACTS_DIR"
  export ARTIFACTS_DIR="$orig_artifacts/$label"
  mkdir -p "$ARTIFACTS_DIR"

  set +e
  python -m pytest \
    --junitxml="$ARTIFACTS_DIR/results.xml" \
    -v \
    > "/tmp/${label}_stdout.log" 2> "/tmp/${label}_stderr.log"
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
# STEP 1: Apply test patch (setup — not a criterion)
# ============================================================
HAS_TEST_PATCH="false"
if [ -f "$EVAL_DIR/test_patch.diff" ]; then
  git apply -v "$EVAL_DIR/test_patch.diff" 2>/dev/null || true
  HAS_TEST_PATCH="true"
fi

# ============================================================
# CRITERION 1: compilation (pip install)
# ============================================================
COMPILE_START=$SECONDS
COMPILE_STATUS="pass"
pip install -e . > /tmp/compile_stdout.log 2> /tmp/compile_stderr.log || {
  COMPILE_STATUS="fail"
}
COMPILE_DURATION=$(_elapsed $COMPILE_START)

# ============================================================
# STEP 3: Run baseline tests (only if test_patch exists and install OK)
# ============================================================
BASELINE_DURATION=0
if [ "$COMPILE_STATUS" = "pass" ] && [ "$HAS_TEST_PATCH" = "true" ]; then
  BASELINE_START=$SECONDS
  _run_tests baseline
  BASELINE_DURATION=$(_elapsed $BASELINE_START)
fi

# ============================================================
# CRITERION 2: patch_applied (submission patch)
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
# STEP 5: Reinstall after submission patch
# ============================================================
REBUILD_STATUS="skipped"
if [ "$COMPILE_STATUS" = "pass" ] && [ "$PATCH_STATUS" = "pass" ]; then
  pip install -e . > /tmp/rebuild_stdout.log 2> /tmp/rebuild_stderr.log || {
    REBUILD_STATUS="fail"
    COMPILE_STATUS="fail"
  }
  if [ "$REBUILD_STATUS" != "fail" ]; then
    REBUILD_STATUS="pass"
  fi
fi

# ============================================================
# STEP 6: Run eval tests (only if compilation and patch OK)
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
_capture_output /tmp/compile_stdout.log > /tmp/_compile_output.txt
_capture_output /tmp/compile_stderr.log >> /tmp/_compile_output.txt

# ============================================================
# Emit EE-bench JSON v2.0 (6 criteria)
# ============================================================
export PATCH_STATUS PATCH_DURATION COMPILE_STATUS COMPILE_DURATION
export TEST_DURATION BASELINE_DURATION OVERALL_DURATION TIMESTAMP
export HAS_TEST_PATCH REBUILD_STATUS

python3 -c "
import json, sys, os

def read_file(path, limit=51200):
    try:
        with open(path) as f:
            return f.read(limit)
    except Exception:
        return ''

def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

patch_status = os.environ.get('PATCH_STATUS', 'pass')
patch_duration = int(os.environ.get('PATCH_DURATION', '0'))
compile_status = os.environ.get('COMPILE_STATUS', 'pass')
compile_duration = int(os.environ.get('COMPILE_DURATION', '0'))
test_duration = int(os.environ.get('TEST_DURATION', '0'))
baseline_duration = int(os.environ.get('BASELINE_DURATION', '0'))
overall_duration = int(os.environ.get('OVERALL_DURATION', '0'))
timestamp = os.environ.get('TIMESTAMP', '')
has_test_patch = os.environ.get('HAS_TEST_PATCH', 'false') == 'true'
rebuild_status = os.environ.get('REBUILD_STATUS', 'skipped')

patch_output = read_file('/tmp/_patch_output.txt')
compile_output = read_file('/tmp/_compile_output.txt')

# Load parser results for baseline and eval
baseline_data = load_json('/tmp/baseline_parser.json')
eval_data = load_json('/tmp/eval_parser.json')

baseline_passed = {t['name'] for t in baseline_data.get('passed_tests', []) if isinstance(t, dict)}
eval_passed = {t['name'] for t in eval_data.get('passed_tests', []) if isinstance(t, dict)}

# Expected test lists (baked in at template render time)
expected_f2p = {{ instance.expected.fail_to_pass | tojson }}
expected_p2p = {{ instance.expected.pass_to_pass | tojson }}

# --- Criterion: baseline_tests ---
if has_test_patch and compile_status == 'pass':
    baseline_status = 'pass'
else:
    baseline_status = 'skipped'

# --- Criterion: tests (eval run) ---
if compile_status != 'pass' or patch_status not in ('pass', 'skipped'):
    tests_status = 'skipped'
else:
    eval_summary = eval_data.get('summary', {})
    tests_status = 'fail' if eval_summary.get('failed', 0) > 0 else 'pass'

# --- Criterion: fail_to_pass ---
if not expected_f2p:
    f2p_status = 'skipped'
    f2p_detail = 'no expected fail_to_pass tests'
elif compile_status != 'pass' or patch_status not in ('pass', 'skipped'):
    f2p_status = 'skipped'
    f2p_detail = 'skipped due to compilation or patch failure'
else:
    f2p_ok = all(t in eval_passed for t in expected_f2p)
    if has_test_patch:
        f2p_baseline_ok = all(t not in baseline_passed for t in expected_f2p)
    else:
        f2p_baseline_ok = True
    f2p_status = 'pass' if (f2p_ok and f2p_baseline_ok) else 'fail'
    detail_parts = []
    if not f2p_ok:
        missing = [t for t in expected_f2p if t not in eval_passed]
        detail_parts.append('eval missing: ' + ', '.join(missing[:10]))
    if not f2p_baseline_ok:
        unexpected = [t for t in expected_f2p if t in baseline_passed]
        detail_parts.append('baseline unexpected pass: ' + ', '.join(unexpected[:10]))
    f2p_detail = '; '.join(detail_parts) if detail_parts else 'all fail_to_pass tests fixed'

# --- Criterion: pass_to_pass ---
if not expected_p2p:
    p2p_status = 'skipped'
    p2p_detail = 'no expected pass_to_pass tests'
elif compile_status != 'pass' or patch_status not in ('pass', 'skipped'):
    p2p_status = 'skipped'
    p2p_detail = 'skipped due to compilation or patch failure'
else:
    p2p_eval_ok = all(t in eval_passed for t in expected_p2p)
    if has_test_patch:
        p2p_baseline_ok = all(t in baseline_passed for t in expected_p2p)
    else:
        p2p_baseline_ok = True
    p2p_status = 'pass' if (p2p_eval_ok and p2p_baseline_ok) else 'fail'
    detail_parts = []
    if not p2p_eval_ok:
        regressed = [t for t in expected_p2p if t not in eval_passed]
        detail_parts.append('eval regressions: ' + ', '.join(regressed[:10]))
    if not p2p_baseline_ok:
        baseline_missing = [t for t in expected_p2p if t not in baseline_passed]
        detail_parts.append('baseline missing: ' + ', '.join(baseline_missing[:10]))
    p2p_detail = '; '.join(detail_parts) if detail_parts else 'all pass_to_pass tests still passing'

# --- Overall status ---
has_failure = any(
    s == 'fail' for s in [compile_status, patch_status, f2p_status, p2p_status]
)
overall_status = 'failure' if has_failure else 'success'

# --- Build eval test output/summary ---
eval_summary = eval_data.get('summary', {
    'total': 0, 'passed': 0, 'failed': 0, 'errors': 0, 'skipped': 0, 'duration_seconds': 0.0,
})
eval_test_output = read_file('/tmp/eval_stdout.log') + read_file('/tmp/eval_stderr.log')

result = {
    'schema_version': '2.0',
    'status': overall_status,
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
            'passed_tests': list(baseline_passed),
            'failed_tests': baseline_data.get('failed_tests', []),
        },
        {
            'criterion': 'patch_applied',
            'status': patch_status,
            'duration_seconds': patch_duration,
            'output': patch_output[:51200],
        },
        {
            'criterion': 'tests',
            'status': tests_status,
            'duration_seconds': test_duration,
            'output': eval_test_output[:51200],
            'summary': eval_summary,
            'passed_tests': eval_data.get('passed_tests', []),
            'failed_tests': eval_data.get('failed_tests', []),
            'skipped_tests': eval_data.get('skipped_tests', []),
            'methods': eval_data.get('methods', []),
        },
        {
            'criterion': 'fail_to_pass',
            'status': f2p_status,
            'expected': expected_f2p,
            'detail': f2p_detail,
        },
        {
            'criterion': 'pass_to_pass',
            'status': p2p_status,
            'expected': expected_p2p,
            'detail': p2p_detail,
        },
    ],
}
print(json.dumps(result))
"
