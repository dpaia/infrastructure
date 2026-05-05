#!/usr/bin/env bash

EE_IMPORT_DIR="/Users/Anton.Spilnyy/work/dpai/ee-bench-import"  #/path/to/ee-bench-import
INFRA_DIR=$(cd ../.. && pwd) #/path/to/infrastructure

if [ -z "$INFRA_DIR" ]; then
    echo "INFRA_DIR must be set and non-empty" >&2
    exit 1
fi

# Build wheel
cd "$EE_IMPORT_DIR" && uv build --wheel
cp dist/ee_bench-*.whl "$INFRA_DIR/.github/tools/"

# Copy scripts
cp "$EE_IMPORT_DIR/scripts/validate.sh" "$INFRA_DIR/.github/scripts/validate.sh"
cp "$EE_IMPORT_DIR/scripts/export_unified.py" "$INFRA_DIR/.github/scripts/export/codegen/export_unified.py"
cp "$EE_IMPORT_DIR/scripts/import_csharp.py" "$INFRA_DIR/.github/scripts/export/codegen/export_unified_csharp.py"
cp "$EE_IMPORT_DIR/scripts/import_swe_bench_pro.py" "$INFRA_DIR/.github/scripts/export/codegen/export_swe_bench_pro.py"