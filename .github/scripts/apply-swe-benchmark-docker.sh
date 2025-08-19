#!/bin/bash

# Usage: ./apply-swe-benchmark-docker.sh <instance_json> [--cleanup] [--by-repo]

set -e

INSTANCE_JSON="$1"

# Parse optional parameters
CLEANUP_CONTAINERS=false
NAME_BY_REPO=false

for arg in "${@:2}"; do
  case $arg in
    --cleanup)
      CLEANUP_CONTAINERS=true
      shift
      ;;
    --by-repo)
      NAME_BY_REPO=true
      shift
      ;;
    --help|-h)
      echo "Usage: $0 <instance_json> [options]"
      echo ""
      echo "Arguments:"
      echo "  <instance_json>  Complete JSON object for a single instance"
      echo ""
      echo "Options:"
      echo "  --cleanup    Remove prepared containers after execution"
      echo "  --by-repo    Name containers by repository instead of instance ID"
      echo "  --help, -h   Show this help message"
      echo ""
      echo "Examples:"
      echo "  $0 '{\"instance_id\":\"instance-123\",\"repo\":\"owner/repo\",...}'"
      echo "  $0 '{\"instance_id\":\"instance-123\",\"repo\":\"owner/repo\",...}' --cleanup"
      echo "  $0 '{\"instance_id\":\"instance-123\",\"repo\":\"owner/repo\",...}' --by-repo"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

if [[ -z "$INSTANCE_JSON" ]]; then
  echo "Usage: $0 <instance_json> [--cleanup] [--by-repo]"
  echo "Use --help for more information"
  exit 1
fi

# Direct JSON mode - extract fields directly
echo "📋 Processing direct JSON input..."
# Extract fields from JSON
INSTANCE_ID=$(echo "$INSTANCE_JSON" | jq -r '.instance_id')
REPO=$(echo "$INSTANCE_JSON" | jq -r '.repo')
COMMIT=$(echo "$INSTANCE_JSON" | jq -r '.base_commit')
PATCH=$(echo "$INSTANCE_JSON" | jq -r '.patch')
TEST_PATCH=$(echo "$INSTANCE_JSON" | jq -r '.test_patch')
FAIL_TO_PASS=$(echo "$INSTANCE_JSON" | jq -r '.FAIL_TO_PASS')
PASS_TO_PASS=$(echo "$INSTANCE_JSON" | jq -r '.PASS_TO_PASS')
IS_MAVEN=$(echo "$INSTANCE_JSON" | jq -r '.is_maven')
JAVA_VERSION=$(echo "$INSTANCE_JSON" | jq -r '.java_version')
TEST_ARGS=$(echo "$INSTANCE_JSON" | jq -r '.test_args')
# Convert is_maven to lowercase
IS_MAVEN=$(echo "$IS_MAVEN" | tr '[:upper:]' '[:lower:]')


# If instance_id isn't in the JSON, generate one based on repository
if [[ -z "$INSTANCE_ID" || "$INSTANCE_ID" == "null" ]]; then
  INSTANCE_ID="auto-$(basename "$REPO" | tr '[:upper:]' '[:lower:]')-$(date +%s)"
  echo "ℹ️ Auto-generated instance ID: $INSTANCE_ID"
fi

# Check if verify_dataset_instance.sh script exists
if [ ! -f ".github/scripts/verify_java_dataset_instance.sh" ]; then
  echo "❌ verify_java_dataset_instance.sh script not found. Please ensure it exists in the current directory."
  exit 1
fi

# Make sure the script is executable
chmod +x .github/scripts/verify_java_dataset_instance.sh

# Run the test dataset instance script with all required parameters
echo "🚀 Running test dataset instance script..."
.github/scripts/verify_java_dataset_instance.sh \
  "$REPO" \
  "$COMMIT" \
  "$PATCH" \
  "$TEST_PATCH" \
  "$FAIL_TO_PASS" \
  "$PASS_TO_PASS" \
  "$TEST_ARGS" \
  "$IS_MAVEN" \
  "$JAVA_VERSION" \
  "$INSTANCE_ID" \
  "$NAME_BY_REPO" \
  "$CLEANUP_CONTAINERS"

exit $?