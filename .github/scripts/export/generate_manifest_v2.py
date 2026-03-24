#!/usr/bin/env python3
"""Generate a manifest.json for an exported dataset.

Usage:
    PYTHONPATH=.github/scripts/export python .github/scripts/export/generate_manifest_v2.py \\
        --exported-ids-file ./export-output/exported-ids.txt \\
        --eval-type codegen \\
        --format folders \\
        --query 'label:"Language: C#"' \\
        --dataset-commit "$(git -C dataset-checkout rev-parse HEAD)" \\
        --output-dir ./export-output
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Generate export manifest")
    parser.add_argument("--exported-ids-file", required=True, help="File with exported instance IDs")
    parser.add_argument("--eval-type", default="codegen", help="Eval type")
    parser.add_argument("--format", choices=["folders", "jsonl"], default="folders")
    parser.add_argument("--query", default="", help="Search query used")
    parser.add_argument("--dataset-commit", default="", help="Dataset repo commit SHA")
    parser.add_argument("--output-dir", required=True, help="Output directory for manifest.json")

    args = parser.parse_args()

    exported_ids_file = Path(args.exported_ids_file)
    output_dir = Path(args.output_dir)

    # Read exported IDs
    if exported_ids_file.is_file():
        instance_ids = [line.strip() for line in exported_ids_file.read_text().splitlines() if line.strip()]
    else:
        instance_ids = []

    manifest = {
        "eval_type": args.eval_type,
        "format": args.format,
        "search_query": args.query,
        "dataset_repo_ref": "main",
        "dataset_repo_commit": args.dataset_commit,
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "datapoint_count": len(instance_ids),
        "instance_ids": instance_ids,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"Manifest written to {manifest_path}")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()