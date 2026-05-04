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

echo "Mode $MODE, instance_id=$INSTANCE_ID"

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

  # Validate required directories exist
  for reqdir in environment eval; do
    if [ ! -d "$INSTANCE_DIR/$reqdir" ]; then
      echo "FAIL: required directory '$reqdir/' missing in instance"
      echo "JSON output:"
      echo "{\"schema_version\":\"2.0\",\"status\":\"failure\",\"timestamp\":\"\",\"duration_seconds\":0,\"criteria\":[{\"criterion\":\"instance_structure\",\"status\":\"fail\",\"detail\":\"required directory '$reqdir/' not found in instance\"}]}"
      exit 1
    fi
  done

  cp -r "$INSTANCE_DIR/eval/"* "$STAGE_DIR/eval/"
  if [ -d "$INSTANCE_DIR/verify" ]; then
    cp -r "$INSTANCE_DIR/verify/"* "$STAGE_DIR/submission/" 2>/dev/null || true
  fi

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
IMAGE_NAME="${INSTANCE_ID,,}:${COMMIT_SHORT}"

# ─── Read per-datapoint docker run params ───────────────────────────────

DOCKER_RUN_PARAMS=""
if [ -f "$INSTANCE_DIR/datapoint.json" ]; then
  RUN_PARAMS_TYPE="$(jq -r '.environment.docker.run_params | type' "$INSTANCE_DIR/datapoint.json" 2>/dev/null || echo "null")"

  if [ "$RUN_PARAMS_TYPE" = "object" ]; then
    # Structured format: convert object fields to docker CLI flags
    _rp='.environment.docker.run_params'

    # --privileged
    if [ "$(jq -r "${_rp}.privileged // false" "$INSTANCE_DIR/datapoint.json")" = "true" ]; then
      DOCKER_RUN_PARAMS+=" --privileged"
    fi

    # --network
    _net="$(jq -r "${_rp}.network // empty" "$INSTANCE_DIR/datapoint.json")"
    if [ -n "$_net" ]; then
      DOCKER_RUN_PARAMS+=" --network $_net"
    fi

    # -v (volumes array)
    while IFS= read -r vol; do
      [ -n "$vol" ] && DOCKER_RUN_PARAMS+=" -v $vol"
    done < <(jq -r "${_rp}.volumes // [] | .[]" "$INSTANCE_DIR/datapoint.json")

    # -e (environment object)
    while IFS= read -r line; do
      [ -n "$line" ] && DOCKER_RUN_PARAMS+=" -e $line"
    done < <(jq -r "${_rp}.environment // {} | to_entries[] | \"\(.key)=\(.value)\"" "$INSTANCE_DIR/datapoint.json")

  elif [ "$RUN_PARAMS_TYPE" = "string" ]; then
    # Legacy string format: pass through as-is
    DOCKER_RUN_PARAMS="$(jq -r '.environment.docker.run_params // empty' "$INSTANCE_DIR/datapoint.json")"
  fi
fi

# ─── Build Docker image (skip if already present) ──────────────────────

# Inject GitHub token into git clone URLs for private repos
if [ -n "${GH_TOKEN:-}" ]; then
  REPO_SLUG=$(jq -r '.repo // empty' "$INSTANCE_DIR/datapoint.json" 2>/dev/null || true)
  if [ -n "$REPO_SLUG" ]; then
    REPO_VISIBILITY=$(gh repo view "$REPO_SLUG" --json visibility -q '.visibility' 2>/dev/null || echo "PUBLIC")
    if [ "$REPO_VISIBILITY" = "PRIVATE" ]; then
      echo "Private repo detected ($REPO_SLUG), injecting auth token for git clone ..."
      sed -i "s|git clone https://github.com/|git clone https://x-access-token:${GH_TOKEN}@github.com/|g" "$DOCKERFILE_DIR/Dockerfile"
    fi
  fi
fi

echo "Building image $IMAGE_NAME ..."
docker rmi "$IMAGE_NAME" &>/dev/null || true
BUILD_LOG="${STAGE_DIR}/build.log"
set +e
docker build --platform linux/amd64 -t "$IMAGE_NAME" -f "$DOCKERFILE_DIR/Dockerfile" "$DOCKERFILE_DIR" 2>&1 | tee "$BUILD_LOG"
BUILD_EXIT=${PIPESTATUS[0]}
set -e

if [ $BUILD_EXIT -ne 0 ]; then
  echo "FAIL: Docker build failed with exit code $BUILD_EXIT"
  # Extract a concise error from build log for the JSON detail field
  BUILD_ERROR=$(grep -iE "error:|ERROR:|could not find|failed to" "$BUILD_LOG" | tail -3 | tr '\n' ' | ' | head -c 500)
  [ -z "$BUILD_ERROR" ] && BUILD_ERROR="Docker build failed with exit code $BUILD_EXIT"
  echo "JSON output:"
  jq -n --arg detail "$BUILD_ERROR" \
    '{schema_version:"2.0",status:"failure",timestamp:"",duration_seconds:0,criteria:[{criterion:"docker_build",status:"fail",detail:$detail}]}'
  exit 1
fi

# ─── Dump eval folder ─────────────────────────────────────

echo ""
echo "--- Dump eval folder ---"
ls -alR "$STAGE_DIR/eval"
echo "--- End dump eval folder ---"
echo "--- Cat patches ---"
find . -type f -name "test_patch.diff" -print0 | while IFS= read -r -d '' f; do
  echo "===== test_patch: $f ====="
  cat "$f"
done
find . -type f -name "patch.diff" -print0 | while IFS= read -r -d '' f; do
  echo "===== patch: $f ====="
  cat "$f"
done
echo "--- End cat patches ---"
echo ""
echo ""

# ─── Run container with gold patch ─────────────────────────────────────

echo "Running validation ..."
# shellcheck disable=SC2086
set +e
OUTPUT=$(docker run --rm --platform linux/amd64 \
  -v "$STAGE_DIR/eval":/ee-bench/eval:ro \
  -v "$STAGE_DIR/submission":/ee-bench/submission:ro \
  $DOCKER_RUN_PARAMS \
  "$IMAGE_NAME" \
  bash /ee-bench/eval/run.sh 2>&1)
DOCKER_EXIT=$?
set -e

if [ $DOCKER_EXIT -ne 0 ]; then
  echo "WARN: docker run exited with code $DOCKER_EXIT"
  echo "$OUTPUT"
fi

# ─── Print container output ─────────────────────────────────────

echo ""
echo "--- Container output ---"
echo "$OUTPUT"
echo "--- End container output ---"
echo ""

# ─── Parse JSON output ─────────────────────────────────────────────────

JSON=$(echo "$OUTPUT" | grep '"schema_version"' || true)

if [ -z "$JSON" ]; then
  echo "FAIL: No JSON output from run.sh (docker exit code: $DOCKER_EXIT)"
  echo "--- Container output ---"
  echo "$OUTPUT"
  echo "--- End container output ---"
  # Emit a structured failure JSON so the workflow can report details
  echo "JSON output:"
  echo "{\"schema_version\":\"2.0\",\"status\":\"failure\",\"timestamp\":\"\",\"duration_seconds\":0,\"criteria\":[{\"criterion\":\"container_execution\",\"status\":\"fail\",\"detail\":\"run.sh failed with exit code $DOCKER_EXIT\"}]}"
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
