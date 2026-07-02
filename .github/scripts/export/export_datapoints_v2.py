#!/usr/bin/env python3
"""Export datapoints from dataset checkout to output directory.

Reads instance IDs from a file, locates each in the dataset directory,
and copies them as folders or appends to a JSONL file.

Usage:
    # As folders:
    PYTHONPATH=.github/scripts/export python .github/scripts/export/export_datapoints_v2.py \\
        --ids-file ./instance-ids.txt \\
        --eval-type codegen \\
        --dataset-dir ./dataset-checkout \\
        --format folders \\
        --output-dir ./export-output \\
        --output-name my-dataset

    # As JSONL:
    PYTHONPATH=.github/scripts/export python .github/scripts/export/export_datapoints_v2.py \\
        --ids-file ./instance-ids.txt \\
        --eval-type codegen \\
        --dataset-dir ./dataset-checkout \\
        --format jsonl \\
        --output-dir ./export-output \\
        --output-name my-dataset
"""

import argparse
import fnmatch
import json
import shutil
import sys
from pathlib import Path


def _find_harbor_instance_dirs(instance_id: str, dataset_dir: Path) -> list[Path]:
    """Locate Harbor task dirs, preferring converted over manual for duplicates."""
    roots = [
        dataset_dir / "_harbor_converted",
        dataset_dir / "_harbor_manual",
    ]
    matches: list[Path] = []
    seen: set[str] = set()

    for root in roots:
        if not root.is_dir():
            continue

        for candidate in sorted(path for path in root.rglob("*") if path.is_dir()):
            if not _is_harbor_task_dir(candidate) or not fnmatch.fnmatch(
                candidate.name, instance_id
            ):
                continue
            if candidate.name in seen:
                continue
            matches.append(candidate)
            seen.add(candidate.name)

    return matches


def _is_harbor_task_dir(path: Path) -> bool:
    return (path / "task.toml").is_file()


def find_instance_dir(
    instance_id: str, eval_type: str, dataset_dir: Path, output_format: str = "folders"
) -> Path | None:
    """Locate an instance directory in the dataset checkout."""
    if output_format == "harbor":
        matches = _find_harbor_instance_dirs(instance_id, dataset_dir)
        return matches[0] if matches else None

    if eval_type == "all":
        search_root = dataset_dir
    else:
        search_root = dataset_dir / eval_type

    if not search_root.is_dir():
        return None

    # Search for the instance directory by name
    for candidate in search_root.rglob(instance_id):
        if candidate.is_dir():
            return candidate

    return None


def find_instance_dirs(
    instance_id: str, eval_type: str, dataset_dir: Path, output_format: str
) -> list[tuple[str, Path]]:
    """Locate one or more instance directories for an ID or glob selector."""
    if output_format == "harbor":
        return [
            (candidate.name, candidate)
            for candidate in _find_harbor_instance_dirs(instance_id, dataset_dir)
        ]

    found = find_instance_dir(instance_id, eval_type, dataset_dir, output_format)
    return [(instance_id, found)] if found else []


def export_folders(instance_id: str, instance_src: Path, output_dir: Path) -> bool:
    """Copy instance directory to output."""
    dest = output_dir / instance_id
    try:
        shutil.copytree(instance_src, dest, dirs_exist_ok=True)
        return True
    except Exception as e:
        print(f"  Error copying {instance_id}: {e}", file=sys.stderr)
        return False


def export_jsonl(instance_id: str, instance_src: Path, jsonl_path: Path) -> bool:
    """Append datapoint.json content to JSONL file."""
    datapoint = instance_src.parent / f"{instance_id}.json"
    if not datapoint.is_file():
        print(f"  Warning: no datapoint.json in {instance_src}", file=sys.stderr)
        return False

    try:
        data = json.loads(datapoint.read_text())
        with open(jsonl_path, "a") as f:
            f.write(json.dumps(data, separators=(",", ":")) + "\n")
        return True
    except Exception as e:
        print(f"  Error processing {instance_id}: {e}", file=sys.stderr)
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export datapoints from dataset checkout"
    )
    parser.add_argument(
        "--ids-file", required=True, help="File with instance IDs (one per line)"
    )
    parser.add_argument("--eval-type", default="codegen", help="Eval type directory")
    parser.add_argument(
        "--dataset-dir", required=True, help="Path to dataset checkout directory"
    )
    parser.add_argument(
        "--format",
        choices=["folders", "jsonl", "harbor"],
        default="folders",
        help="Output format",
    )
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument(
        "--output-name", default="dataset", help="Output name (used for JSONL filename)"
    )
    parser.add_argument(
        "--exported-ids-file", default=None, help="File to write exported instance IDs"
    )
    parser.add_argument(
        "--skipped-ids-file", default=None, help="File to write skipped instance IDs"
    )

    args = parser.parse_args(argv)

    ids_file = Path(args.ids_file)
    dataset_dir = Path(args.dataset_dir)
    output_dir = Path(args.output_dir)

    if not ids_file.is_file():
        print(f"Error: IDs file not found: {ids_file}", file=sys.stderr)
        return 1

    if not dataset_dir.is_dir():
        print(f"Error: dataset directory not found: {dataset_dir}", file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    # Read instance IDs
    instance_ids = [
        line.strip() for line in ids_file.read_text().splitlines() if line.strip()
    ]
    print(f"Processing {len(instance_ids)} instance IDs")

    exported = []
    skipped = []
    exported_seen = set()
    jsonl_path = output_dir / f"{args.output_name}.jsonl"

    for instance_id in instance_ids:
        matches = find_instance_dirs(
            instance_id, args.eval_type, dataset_dir, args.format
        )

        if not matches:
            print(f"  Skip: {instance_id} — not found in dataset")
            skipped.append(instance_id)
            continue

        for exported_id, instance_src in matches:
            if exported_id in exported_seen:
                continue
            if args.format in {"folders", "harbor"}:
                ok = export_folders(exported_id, instance_src, output_dir)
            else:
                ok = export_jsonl(exported_id, instance_src, jsonl_path)

            if ok:
                exported.append(exported_id)
                exported_seen.add(exported_id)
            else:
                skipped.append(exported_id)

    # Write exported IDs
    exported_ids_file = args.exported_ids_file or str(output_dir / "exported-ids.txt")
    Path(exported_ids_file).write_text("\n".join(exported) + "\n" if exported else "")
    skipped_ids_file = args.skipped_ids_file or str(output_dir / "skipped-ids.txt")
    Path(skipped_ids_file).write_text("\n".join(skipped) + "\n" if skipped else "")

    print(f"\nExported {len(exported)} datapoints, skipped {len(skipped)}")

    # Write count to stdout for workflow capture
    print(f"EXPORT_COUNT={len(exported)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
