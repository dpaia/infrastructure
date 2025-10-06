#!/bin/bash

# SWE-Bench Docker Evaluation Script
#
# This script runs SWE-bench evaluations and produces verification results.
# It handles both successful and failed evaluations, parsing the detailed
# JSON reports produced by the evaluation framework.
#
# Usage: ./apply-swe-benchmark-docker.sh <instance_json> [--generator=<name>]
#
# Arguments:
#   <instance_json>  Complete JSON object for a single SWE-bench instance
#
# Options:
#   --generator=<name>   Selects the spec for evaluation (default: swe-jvm)
#   --help, -h           Show help message
#
# Output:
#   - Saves instance JSON to datasets/<generator>/<instance_id>.json
#   - Runs evaluation via run_validation.sh
#   - Parses evaluation report from reports/<instance_id>.json
#   - Writes verification-result.json with status and message
#   - Returns exit code 0 for success, 1 for failure
#
# Report Format:
#   The script expects reports in the format:
#   {
#     "results": {
#       "<instance_id>": {
#         "result": "success|failed",
#         "successful": true|false,
#         "message": "...",
#         "error": "...",
#         "evaluations": { ... }
#       }
#     }
#   }
#
# Note: We don't use 'set -e' here to allow proper error handling and exit code capture

# Helper to write verification result to JSON
write_verification_result_json() {
  local status="$1"
  local message="$2"
  local outfile="verification-result.json"

  if command -v jq >/dev/null 2>&1; then
    if [[ -n "$message" ]]; then
      jq -n --arg result "$status" --arg message "$message" '{result:$result, message:$message}' > "$outfile"
    else
      jq -n --arg result "$status" '{result:$result}' > "$outfile"
    fi
  else
    local esc_message="${message//\"/\\\"}"
    if [[ -n "$message" ]]; then
      printf '{"result":"%s","message":"%s"}\n' "$status" "$esc_message" > "$outfile"
    else
      printf '{"result":"%s"}\n' "$status" > "$outfile"
    fi
  fi
  echo "📄 Saved verification result to $outfile"
}

# Check for help flag first
for arg in "$@"; do
  case $arg in
    --help|-h)
      echo "Usage: $0 <instance_json> [options]"
      echo ""
      echo "Arguments:"
      echo "  <instance_json>  Complete JSON object for a single instance"
      echo ""
      echo "Options:"
      echo "  --generator=<name>   Selects the spec for evaluation (default: swe-jvm)"
      echo "  --help, -h           Show this help message"
      echo ""
      echo "Examples:"
      echo "  $0 '{\"instance_id\":\"instance-123\",\"repo\":\"owner/repo\",...}'"
      echo "  $0 '{\"instance_id\":\"instance-123\",\"repo\":\"owner/repo\",...}' --generator=swe-jvm"
      exit 0
      ;;
  esac
done

INSTANCE_JSON="$1"

# Parse optional parameters
GENERATOR="swe-jvm"

for arg in "${@:2}"; do
  case $arg in
    --generator=*)
      GENERATOR="${arg#*=}"
      ;;
    --generator)
      echo "Error: --generator requires a value. Use --generator=<name>"
      exit 1
      ;;
    *)
      echo "Unknown option: $arg"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

if [[ -z "$INSTANCE_JSON" ]]; then
  echo "Usage: $0 <instance_json> [--generator=<name>]"
  echo "Use --help for more information"
  write_verification_result_json "failed" "No instance JSON provided"
  exit 1
fi

# Direct JSON mode - extract fields directly
echo "📋 Processing direct JSON input..."
# Extract instance_id and repo for validation
INSTANCE_ID=$(echo "$INSTANCE_JSON" | jq -r '.instance_id')
REPO=$(echo "$INSTANCE_JSON" | jq -r '.repo')

# If instance_id isn't in the JSON, generate one based on repository
if [[ -z "$INSTANCE_ID" || "$INSTANCE_ID" == "null" ]]; then
  INSTANCE_ID="auto-$(basename "$REPO" | tr '[:upper:]' '[:lower:]')-$(date +%s)"
  echo "ℹ️ Auto-generated instance ID: $INSTANCE_ID"
fi

echo "🧰 Generator selected: ${GENERATOR}"

# Prepare dataset directory and save instance JSON
DATASET_DIR="datasets/${GENERATOR}"
mkdir -p "$DATASET_DIR"
INSTANCE_FILE="${DATASET_DIR}/${INSTANCE_ID}.json"

echo "💾 Saving instance JSON to $INSTANCE_FILE"
echo "$INSTANCE_JSON" > "$INSTANCE_FILE"

# Run the evaluation script
EVALUATION_SCRIPT="$(dirname "$0")/run_validation.sh"
if [ ! -f "$EVALUATION_SCRIPT" ]; then
  echo "❌ Evaluation script not found at $EVALUATION_SCRIPT"
  write_verification_result_json "failed" "Evaluation script not found"
  exit 1
fi

chmod +x "$EVALUATION_SCRIPT"

echo "🚀 Running evaluation script: $EVALUATION_SCRIPT"
"$EVALUATION_SCRIPT" swe-jvm \
  --dataset-name "$INSTANCE_FILE" \
  --run-id "$INSTANCE_ID" \
  --report-dir .

EVAL_EXIT_CODE=$?

echo ""
echo "========================================="
echo "Evaluation completed with exit code: $EVAL_EXIT_CODE"
echo "========================================="

# Determine the report file location
# The report should be in reports/ or core/reports/ directory
REPORT_FILE="${INSTANCE_ID}.json"

if [ -z "$REPORT_FILE" ]; then
  echo "❌ Report file not found for instance: ${INSTANCE_ID}"
  write_verification_result_json "failed" "Evaluation report file not found"
  exit 1
fi

# Parse the new report format
# Report structure: { "results": { "instance_id": { "result": "success|failed", "message": "...", "successful": true|false } } }

RESULT_STATUS=$(jq -r ".results[\"$INSTANCE_ID\"].result // \"unknown\"" "$REPORT_FILE")
SUCCESSFUL=$(jq -r ".results[\"$INSTANCE_ID\"].successful // false" "$REPORT_FILE")
MESSAGE=$(jq -r ".results[\"$INSTANCE_ID\"].message // \"No message provided\"" "$REPORT_FILE")

echo ""
echo "========================================="
echo "Report Analysis:"
echo "  Instance ID: $INSTANCE_ID"
echo "  Result: $RESULT_STATUS"
echo "  Successful: $SUCCESSFUL"
echo "  Message: $MESSAGE"
echo "========================================="

# Check if evaluation was successful
if [ "$EVAL_EXIT_CODE" -eq 0 ] && [ "$SUCCESSFUL" = "true" ] && [ "$RESULT_STATUS" = "success" ]; then
  echo "✅ Instance resolved successfully"
  write_verification_result_json "ok" "Validation passed: $MESSAGE"
  exit 0
else
  echo "❌ Instance failed to resolve"

  # Build detailed failure message from report
  FAILURE_MESSAGE="$MESSAGE"

  # Check for specific evaluator failures
  EVALUATOR_ERRORS=$(jq -r ".results[\"$INSTANCE_ID\"].evaluations | to_entries | map(select(.value.status == \"error\" or .value.status == \"failed\")) | map(\"\(.key): \(.value.message)\") | join(\"; \")" "$REPORT_FILE" 2>/dev/null)

  if [ -n "$EVALUATOR_ERRORS" ] && [ "$EVALUATOR_ERRORS" != "null" ] && [ "$EVALUATOR_ERRORS" != "" ]; then
    FAILURE_MESSAGE="$FAILURE_MESSAGE | Evaluator failures: $EVALUATOR_ERRORS"
  fi

  # Add error field if present
  ERROR_INFO=$(jq -r ".results[\"$INSTANCE_ID\"].error // empty" "$REPORT_FILE")
  if [ -n "$ERROR_INFO" ] && [ "$ERROR_INFO" != "null" ]; then
    FAILURE_MESSAGE="$FAILURE_MESSAGE | Error: $ERROR_INFO"
  fi

  write_verification_result_json "failed" "$FAILURE_MESSAGE"
  exit 1
fi