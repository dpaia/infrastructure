#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${EE_BENCH_PROJECT_ROOT:-/repo}"
EVAL_DIR="/ee-bench/eval"
SUBMISSION_DIR="/ee-bench/submission"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
OVERALL_START=$SECONDS

cd "$PROJECT_ROOT"

CUSTOM_VALIDATOR=""
if [ -f "$EVAL_DIR/scripts/validate_method.py" ]; then
  CUSTOM_VALIDATOR="$EVAL_DIR/scripts/validate_method.py"
fi

python3 "$EVAL_DIR/scripts/ee_bench_methodgen.py" \
  --project-root "$PROJECT_ROOT" \
  --patch "$SUBMISSION_DIR/patch.diff" \
  --target '{"language": {{ instance.language | tojson }}, "target": {"file": {{ instance.target.file | tojson }}, "method_signature": {{ instance.target.method_signature | tojson }}, "validations": {{ instance.target.validations | tojson }}}}' \
  --custom-validator "$CUSTOM_VALIDATOR" \
  --timestamp "$TIMESTAMP" \
  --duration-seconds "$((SECONDS - OVERALL_START))"
