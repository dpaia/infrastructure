#!/usr/bin/env bash

# Dataset Verification Script
#
# This script combines dataset validation and SWE-bench evaluation.
# It sets up the environment, runs evaluations, and produces verification results.
#
# Usage: ./verify_dataset.sh <instance_json> [options]
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
#   - Sets up virtual environment and installs wheels
#   - Runs evaluation via ee-bench
#   - Parses evaluation report from <instance_id>.json
#   - Writes verification-result.json with status and message
#   - Returns exit code 0 for success, 1 for failure
#
# Note: We don't use 'set -e' here to allow proper error handling and exit code capture

# Error handling function
error_exit() {
    echo "❌ Error: $1" >&2
    exit "${2:-1}"
}

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
echo "[ $INSTANCE_JSON ]" > "$INSTANCE_FILE"

# Set up paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || error_exit "Failed to determine script directory"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)" || error_exit "Failed to determine project root"
TOOLS_DIR="$SCRIPT_DIR/../tools"

# Check if tools directory exists
if [ ! -d "$TOOLS_DIR" ]; then
    error_exit "Tools directory not found at $TOOLS_DIR" 1
fi

# Find all wheel files in tools directory
WHEEL_FILES=("$TOOLS_DIR"/*.whl)

# Check if any wheel files exist
if [ ${#WHEEL_FILES[@]} -eq 0 ] || [ ! -f "${WHEEL_FILES[0]}" ]; then
    echo "Error: No wheel files found in $TOOLS_DIR"
    echo "Please build the wheels first"
    write_verification_result_json "failed" "No wheel files found in $TOOLS_DIR"
    exit 1
fi

echo "========================================="
echo "EE-Bench Dataset Verification"
echo "========================================="
echo "Project root: $PROJECT_ROOT"
echo "Tools dir:    $TOOLS_DIR"
echo "Wheel files found: ${#WHEEL_FILES[@]}"
for whl in "${WHEEL_FILES[@]}"; do
    echo "  - $(basename "$whl")"
done
echo "========================================="
echo ""

# Create and activate virtual environment if needed
VENV_DIR="$PROJECT_ROOT/.venv-evaluation"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR" || error_exit "Failed to create virtual environment" 2
fi

echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate" || error_exit "Failed to activate virtual environment" 3

# Install/upgrade all wheels (core first with dependencies, then plugins)
echo "Installing all wheels from tools directory..."

# Install ee_bench_core first WITH dependencies
echo "Installing core package with dependencies..."
CORE_INSTALLED=false
for whl in "${WHEEL_FILES[@]}"; do
    if [[ "$(basename "$whl")" == ee_bench_core-*.whl ]]; then
        echo "Installing $(basename "$whl") with dependencies..."
        if ! pip install --force-reinstall "$whl"; then
            error_exit "Failed to install core package: $(basename "$whl")" 4
        fi
        CORE_INSTALLED=true
    fi
done

if [ "$CORE_INSTALLED" = false ]; then
    error_exit "No core package (ee_bench_core-*.whl) found in wheels" 5
fi

# Install remaining wheels WITHOUT dependencies (they only need core)
echo "Installing plugin packages..."
for whl in "${WHEEL_FILES[@]}"; do
    if [[ "$(basename "$whl")" != ee_bench_core-*.whl ]]; then
        echo "Installing $(basename "$whl")..."
        if ! pip install --force-reinstall --no-deps "$whl"; then
            echo "⚠️  Warning: Failed to install $(basename "$whl"), continuing..." >&2
        fi
    fi
done

echo ""
echo "🚀 Starting evaluation..."
echo "========================================="
echo ""

# Run evaluation
(
  set +e
  ee-bench --spec swe-jvm -v run-evaluation \
      --dataset-name "$INSTANCE_FILE" \
      --instance-ids "$INSTANCE_ID" \
      --run-id "$INSTANCE_ID" \
      --predictions-path gold \
      --print-report \
      --report-dir . \
      --docker-opts "-v /var/run/docker.sock:/var/run/docker.sock \
        --privileged \
        --network bridge \
        -e TESTCONTAINERS_RYUK_DISABLED=true \
        -e TESTCONTAINERS_CHECKS_DISABLE=true \
        -e DOCKER_HOST=unix:///var/run/docker.sock"
)
EVAL_EXIT_CODE=$?

echo ""
echo "========================================="
echo "Evaluation completed with exit code: $EVAL_EXIT_CODE"
echo "========================================="

# Determine the report file location
REPORT_FILE="${INSTANCE_ID}.json"

if [ ! -f "$REPORT_FILE" ]; then
  echo "❌ Report file not found for instance: ${INSTANCE_ID}"
  write_verification_result_json "failed" "Evaluation report file not found"
  exit 1
fi

# Parse the report format
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

  write_verification_result_json "failed" "$FAILURE_MESSAGE"
  exit 1
fi
