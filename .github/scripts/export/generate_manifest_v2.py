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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate export manifest")
    parser.add_argument(
        "--exported-ids-file", required=True, help="File with exported instance IDs"
    )
    parser.add_argument("--eval-type", default="codegen", help="Eval type")
    parser.add_argument(
        "--format", choices=["folders", "jsonl", "harbor"], default="folders"
    )
    parser.add_argument("--query", default="", help="Search query used")
    parser.add_argument("--dataset-commit", default="", help="Dataset repo commit SHA")
    parser.add_argument(
        "--skipped-ids-file", default="", help="File with skipped instance IDs"
    )
    parser.add_argument(
        "--output-dir", required=True, help="Output directory for manifest.json"
    )

    args = parser.parse_args(argv)

    exported_ids_file = Path(args.exported_ids_file)
    output_dir = Path(args.output_dir)

    # Read exported IDs
    instance_ids = read_ids(exported_ids_file)
    skipped_ids = read_ids(Path(args.skipped_ids_file)) if args.skipped_ids_file else []

    manifest = {
        "eval_type": args.eval_type,
        "format": args.format,
        "search_query": args.query,
        "dataset_repo_ref": "main",
        "dataset_repo_commit": args.dataset_commit,
        "dataset_commit": args.dataset_commit,
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "datapoint_count": len(instance_ids),
        "instance_ids": instance_ids,
        "matched_instance_ids": instance_ids,
        "skipped_instance_ids": skipped_ids,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"Manifest written to {manifest_path}")
    print(json.dumps(manifest, indent=2))
    return 0


def read_ids(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


if __name__ == "__main__":
    sys.exit(main())
