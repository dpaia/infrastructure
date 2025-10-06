#!/usr/bin/env bash

# Script to run EE-Bench evaluation with pre-built wheel
# Usage: ./scripts/run_validation.sh <spec> [options]
# Example: ./scripts/run_validation.sh swe-jvm --dataset-name dataset.json --run-id test-1

# Error handling function
error_exit() {
    echo "❌ Error: $1" >&2
    exit "${2:-1}"
}

# Parse spec from first argument
SPEC="$1"
if [ -z "$SPEC" ]; then
    error_exit "Usage: $0 <spec> [options]\nExample: $0 swe-jvm --dataset-name dataset.json --run-id test-1" 1
fi

# Shift to get remaining arguments
shift

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || error_exit "Failed to determine script directory"
PROJECT_ROOT="$(cd "$SCRIPT_DIR" && pwd)" || error_exit "Failed to determine project root"
TOOLS_DIR="$SCRIPT_DIR/tools"

# Check if tools directory exists
if [ ! -d "$TOOLS_DIR" ]; then
    error_exit "Tools directory not found at $TOOLS_DIR" 1
fi

# Find all wheel files in tools directory
WHEEL_FILES=("$TOOLS_DIR"/*.whl)

# Check if any wheel files exist
if [ ${#WHEEL_FILES[@]} -eq 0 ] || [ ! -f "${WHEEL_FILES[0]}" ]; then
    echo "Error: No wheel files found in $TOOLS_DIR"
    echo "Please build the wheels first with: ./scripts/build.sh"
    exit 1
fi

echo "========================================="
echo "EE-Bench Evaluation Runner"
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
echo "Starting evaluation..."
echo "========================================="
echo ""

# Run evaluation
(
  set +e
  ee-bench "$SPEC" -v run-evaluation \
      --predictions-path gold \
      --docker-opts "-v /var/run/docker.sock:/var/run/docker.sock \
        --privileged \
        --network bridge \
        -e TESTCONTAINERS_RYUK_DISABLED=true \
        -e TESTCONTAINERS_CHECKS_DISABLE=true \
        -e DOCKER_HOST=unix:///var/run/docker.sock \
        -e TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal" \
      "$@"
)
EXIT_CODE=$?

exit $EXIT_CODE