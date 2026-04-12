#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${EE_BENCH_PROJECT_ROOT:-/repo}"
EVAL_DIR="/ee-bench/eval"
SUBMISSION_DIR="/ee-bench/submission"
export ARTIFACTS_DIR="/tmp/test-results"
mkdir -p "$ARTIFACTS_DIR"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
OVERALL_START=$SECONDS

_elapsed() { echo $(( SECONDS - ${1:-$OVERALL_START} )); }

cd "$PROJECT_ROOT"

# ============================================================
# Criterion: patch_applied (submission patch)
# ============================================================
PATCH_STATUS="pass"
if [ -f "$SUBMISSION_DIR/patch.diff" ]; then
  git apply "$SUBMISSION_DIR/patch.diff" 2>/dev/null || {
    PATCH_STATUS="fail"
  }
else
  PATCH_STATUS="skipped"
fi

# ============================================================
# Apply test patch if present (adds test classes to repo)
# ============================================================
if [ -f "$EVAL_DIR/test_patch.diff" ]; then
  git apply "$EVAL_DIR/test_patch.diff" 2>/dev/null || true
fi

# ============================================================
# Test execution (only if test validation is configured)
# ============================================================
TEST_RESULT_JSON=""
{% set test_validations = instance.target.validations | default([]) | selectattr('type', 'equalto', 'test') | list %}
{% if test_validations | length > 0 %}
{% set test_class = test_validations[0].test_class %}
if [ "$PATCH_STATUS" = "pass" ]; then
  # Compile
  COMPILE_OK="true"
  ./mvnw compile test-compile -q > /tmp/compile_stdout.log 2> /tmp/compile_stderr.log || {
    COMPILE_OK="false"
  }

  if [ "$COMPILE_OK" = "true" ]; then
    # Run tests
    set +e
    ./mvnw test -Dtest={{ test_class | tojson }} -q > /tmp/test_stdout.log 2> /tmp/test_stderr.log
    set -e

    # Collect surefire XML results
    find "$PROJECT_ROOT" -path "*/target/surefire-reports/*.xml" -exec cp {} "$ARTIFACTS_DIR/" \; 2>/dev/null || true

    # Parse JUnit XML
    TEST_RESULT_JSON="/tmp/test_parser.json"
    python3 "$EVAL_DIR/scripts/ee_bench_parser_junit.py" "$ARTIFACTS_DIR" > "$TEST_RESULT_JSON" 2>/dev/null || echo '{}' > "$TEST_RESULT_JSON"
  else
    # Write empty result so evaluator knows compilation failed
    TEST_RESULT_JSON="/tmp/test_parser.json"
    echo '{"summary":{"total":0,"passed":0,"failed":0},"passed_tests":[],"failed_tests":[]}' > "$TEST_RESULT_JSON"
  fi
fi
{% endif %}

# ============================================================
# Evaluate (criteria 1-3)
# ============================================================
python3 "$EVAL_DIR/scripts/ee_bench_methodgen.py" \
  --project-root "$PROJECT_ROOT" \
  --patch-status "$PATCH_STATUS" \
  --target '{"language": {{ instance.language | tojson }}, "target": {"file": {{ instance.target.file | tojson }}, "method_signature": {{ instance.target.method_signature | tojson }}, "validations": {{ instance.target.validations | tojson }}}}' \
  --test-result-json "$TEST_RESULT_JSON" \
  --timestamp "$TIMESTAMP" \
  --duration-seconds "$(_elapsed $OVERALL_START)"
