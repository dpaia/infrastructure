#!/usr/bin/env bash
set -euo pipefail

# ─── Unified validate.sh ───────────────────────────────────────────────
# Usage:
#   bash scripts/validate.sh <instance_dir>
#   bash scripts/validate.sh <dataset.jsonl> <instance_id>
#
# Requires: jq, docker
# ────────────────────────────────────────────────────────────────────────

usage() {
  echo "Usage:"
  echo "  $0 <instance_dir>                   # folder mode"
  echo "  $0 <dataset.jsonl> <instance_id>    # JSONL mode"
  exit 1
}

for cmd in jq docker; do
  command -v "$cmd" &>/dev/null || { echo "Error: $cmd is required but not found"; exit 1; }
done

[ $# -lt 1 ] && usage

# ─── Detect mode ────────────────────────────────────────────────────────

if [ -d "$1" ]; then
  MODE="folder"
  INSTANCE_DIR="$(cd "$1" && pwd)"
  INSTANCE_ID="$(jq -r '.instance_id' "$INSTANCE_DIR/datapoint.json")"
elif [[ "$1" == *.jsonl ]]; then
  MODE="jsonl"
  JSONL_FILE="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
  [ $# -lt 2 ] && { echo "Error: JSONL mode requires an instance_id argument"; usage; }
  INSTANCE_ID="$2"
else
  echo "Error: first argument must be an instance directory or a .jsonl file"
  usage
fi

# ─── Staging directory (macOS Docker mount compatibility) ───────────────

STAGE_DIR="/tmp/ee-bench-validate-${INSTANCE_ID}"
cleanup() { rm -rf "$STAGE_DIR"; }
trap cleanup EXIT

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

# ─── Resolve / materialize instance files ───────────────────────────────

if [ "$MODE" = "folder" ]; then
  DOCKERFILE_DIR="$INSTANCE_DIR/environment"
  mkdir -p "$STAGE_DIR/eval" "$STAGE_DIR/submission"
  cp -r "$INSTANCE_DIR/eval/"* "$STAGE_DIR/eval/"
  cp -r "$INSTANCE_DIR/verify/"* "$STAGE_DIR/submission/"

elif [ "$MODE" = "jsonl" ]; then
  # Extract matching record to a temp file (avoids shell variable escaping issues)
  RECORD_FILE="$STAGE_DIR/record.json"
  jq -c --arg id "$INSTANCE_ID" 'select(.instance_id == $id)' "$JSONL_FILE" > "$RECORD_FILE"

  if [ ! -s "$RECORD_FILE" ]; then
    echo "Error: instance_id \"$INSTANCE_ID\" not found in $JSONL_FILE"
    exit 1
  fi

  INSTANCE_DIR="$STAGE_DIR/instance"

  # Write environment files (from .environment.files sub-key)
  mkdir -p "$INSTANCE_DIR/environment"
  jq -r '.environment.files | keys[]' "$RECORD_FILE" | while IFS= read -r key; do
    dest="$INSTANCE_DIR/environment/$key"
    mkdir -p "$(dirname "$dest")"
    jq -r --arg k "$key" '.environment.files[$k]' "$RECORD_FILE" > "$dest"
  done

  # Write eval files (from .eval.files sub-key)
  jq -r '.eval.files | keys[]' "$RECORD_FILE" | while IFS= read -r key; do
    dest="$INSTANCE_DIR/eval/$key"
    mkdir -p "$(dirname "$dest")"
    jq -r --arg k "$key" '.eval.files[$k]' "$RECORD_FILE" > "$dest"
  done

  # Write gold submission files (from .verify.files sub-key)
  jq -r '.verify.files | keys[]' "$RECORD_FILE" | while IFS= read -r key; do
    dest="$INSTANCE_DIR/verify/$key"
    mkdir -p "$(dirname "$dest")"
    jq -r --arg k "$key" '.verify.files[$k]' "$RECORD_FILE" > "$dest"
  done

  # Write datapoint.json with metadata (paths instead of inline content)
  jq '{
    instance_id,
    repo,
    base_commit,
    problem_statement,
    version,
    created_at,
    project_root,
    environment: ((.environment | del(.files)) + {
      files: (.environment.files | keys | map({ (.): ("environment/" + .) }) | add)
    }),
    eval: {
      files: (.eval.files | keys | map({ (.): ("eval/" + .) }) | add)
    },
    verify: {
      files: (.verify.files | keys | map({ (.): ("verify/" + .) }) | add)
    },
    expected
  }' "$RECORD_FILE" > "$INSTANCE_DIR/datapoint.json"

  rm -f "$RECORD_FILE"

  DOCKERFILE_DIR="$INSTANCE_DIR/environment"
  mkdir -p "$STAGE_DIR/eval" "$STAGE_DIR/submission"
  cp -r "$INSTANCE_DIR/eval/"* "$STAGE_DIR/eval/"
  cp -r "$INSTANCE_DIR/verify/"* "$STAGE_DIR/submission/"
fi

# ─── Docker tag: instance_id as image name, base_commit as tag ────────

BASE_COMMIT="$(jq -r '.base_commit // empty' "$INSTANCE_DIR/datapoint.json")"
COMMIT_SHORT="${BASE_COMMIT:0:12}"
IMAGE_NAME="${INSTANCE_ID}:${COMMIT_SHORT}"

# ─── Read per-datapoint docker run params ───────────────────────────────

DOCKER_RUN_PARAMS=""
if [ -f "$INSTANCE_DIR/datapoint.json" ]; then
  DOCKER_RUN_PARAMS="$(jq -r '.environment.docker.run_params // empty' "$INSTANCE_DIR/datapoint.json")"
fi

# ─── Build Docker image (skip if already present) ──────────────────────

echo "Building image $IMAGE_NAME ..."
docker rmi "$IMAGE_NAME" &>/dev/null || true
docker build --platform linux/amd64 -t "$IMAGE_NAME" -f "$DOCKERFILE_DIR/Dockerfile" "$DOCKERFILE_DIR"

# ─── Run container with gold patch ─────────────────────────────────────

echo "Running validation ..."
# shellcheck disable=SC2086
OUTPUT=$(docker run --rm --platform linux/amd64 \
  -v "$STAGE_DIR/eval":/ee-bench/eval:ro \
  -v "$STAGE_DIR/submission":/ee-bench/submission:ro \
  $DOCKER_RUN_PARAMS \
  "$IMAGE_NAME" \
  bash /ee-bench/eval/run.sh 2>&1)

# ─── Parse JSON output ─────────────────────────────────────────────────

JSON=$(echo "$OUTPUT" | grep '"schema_version"' || true)

if [ -z "$JSON" ]; then
  echo "FAIL: No JSON output from run.sh"
  echo "$OUTPUT"
  exit 1
fi

# ─── Print criteria summary ───────────────────────────────────────────

echo ""
echo "$JSON" | jq -r '.criteria[] | "  \(.criterion): \(.status)"'

# ─── Sanity checks (catch broken templates, empty runs) ──────────────

TESTS_TOTAL=$(echo "$JSON" | jq -r '(.criteria // []) | map(select(.criterion == "tests")) | first | .summary.total // 0')
TESTS_OUTPUT=$(echo "$JSON" | jq -r '(.criteria // []) | map(select(.criterion == "tests")) | first | .output // ""')

# Check for unrendered Jinja2 template variables in output
if echo "$TESTS_OUTPUT" | grep -q '{{ instance\.' 2>/dev/null; then
  echo "FAIL: run.sh contains unrendered Jinja2 template variables"
  echo "This means the template was not properly rendered during export."
  echo ""
  echo "JSON output:"
  echo "$JSON" | jq .
  exit 1
fi

# Check that tests actually ran
if [ "$TESTS_TOTAL" -eq 0 ]; then
  TESTS_STATUS=$(echo "$JSON" | jq -r '(.criteria // []) | map(select(.criterion == "tests")) | first | .status // "skipped"')
  if [ "$TESTS_STATUS" != "skipped" ]; then
    echo "FAIL: tests criterion reports status=$TESTS_STATUS but 0 tests ran"
    echo ""
    echo "JSON output:"
    echo "$JSON" | jq .
    exit 1
  fi
fi

# ─── Final verdict (run.sh self-evaluates; trust its overall status) ──

echo ""
echo "JSON output:"
echo "$JSON" | jq .

STATUS=$(echo "$JSON" | jq -r '.status')
if [ "$STATUS" = "success" ]; then
  exit 0
else
  echo "Validation failed (status=$STATUS)"
  echo "$JSON" | jq -r '[.criteria[] | select(.status == "fail")] | map("  FAIL: \(.criterion) — \(.detail // .output // "")") | .[]' 2>/dev/null || true
  exit 1
fi
