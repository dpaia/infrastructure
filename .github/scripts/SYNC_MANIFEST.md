# ee-bench-import Sync Manifest

Records the provenance of files copied from `dpaia/ee-bench-import` into this repository.

## Source

- **Repository:** `dpaia/ee-bench-import`
- **Commit:** `f94066c27761ae9683a2233c0bd76e23a021062b`
- **Branch:** `main`
- **Synced at:** 2026-03-16

## Copied Artifacts

| Source (ee-bench-import) | Destination (infrastructure) | Purpose |
|--------------------------|------------------------------|---------|
| `scripts/validate.sh` | `.github/scripts/validate.sh` | Unified datapoint validation (folder + JSONL modes) |
| `scripts/export_unified.py` | `.github/scripts/export/codegen/export_unified.py` | Codegen datapoint export script |
| `scripts/import_csharp.py` | `.github/scripts/export/codegen/export_unified_csharp.py` | C# datapoint export (two-pass, dotnet-specific) |
| `scripts/import_swe_bench_pro.py` | `.github/scripts/export/codegen/export_swe_bench_pro.py` | SWE-bench Pro datapoint export (HuggingFace source) |
| `dist/ee_bench-0.1.0-py3-none-any.whl` | `.github/tools/ee_bench-0.1.0-py3-none-any.whl` | Pre-built ee-dataset CLI wheel |

## Local Enhancements

The following infrastructure copies contain local improvements over the ee-bench-import source:

- **`validate.sh`**: Uses `jq --arg` for special character safety
- **`export_unified.py`**: Adds configurable `OUTPUT_DIR` and `filters = None` support

## Refresh Instructions

To update synced files from a newer ee-bench-import commit:

```bash
EE_IMPORT_DIR=/path/to/ee-bench-import
INFRA_DIR=/path/to/infrastructure

# Build wheel
cd "$EE_IMPORT_DIR" && uv build --wheel
cp dist/ee_bench-*.whl "$INFRA_DIR/.github/tools/"

# Copy scripts
cp "$EE_IMPORT_DIR/scripts/validate.sh" "$INFRA_DIR/.github/scripts/validate.sh"
cp "$EE_IMPORT_DIR/scripts/export_unified.py" "$INFRA_DIR/.github/scripts/export/codegen/export_unified.py"
cp "$EE_IMPORT_DIR/scripts/import_csharp.py" "$INFRA_DIR/.github/scripts/export/codegen/export_unified_csharp.py"
cp "$EE_IMPORT_DIR/scripts/import_swe_bench_pro.py" "$INFRA_DIR/.github/scripts/export/codegen/export_swe_bench_pro.py"

# Update this manifest with the new commit SHA and date
# Re-apply local enhancements if overwritten
```
