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

## Refresh Instructions

To update synced files from a newer ee-bench-import commit:

```bash
EE_IMPORT_DIR=/path/to/ee-bench-import
INFRA_DIR=/path/to/infrastructure

cp "$EE_IMPORT_DIR/scripts/validate.sh" "$INFRA_DIR/.github/scripts/validate.sh"
cp "$EE_IMPORT_DIR/scripts/export_unified.py" "$INFRA_DIR/.github/scripts/export/codegen/export_unified.py"

# Update this manifest with the new commit SHA and date
```
