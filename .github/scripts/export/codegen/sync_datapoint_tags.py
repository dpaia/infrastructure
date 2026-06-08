#!/usr/bin/env python3
"""Backfill codegen datapoint tags from GitHub pull request labels.

Examples:
    python .github/scripts/export/codegen/sync_datapoint_tags.py --dry-run
    python .github/scripts/export/codegen/sync_datapoint_tags.py --instance-id dpaia__feature__service-415
    python .github/scripts/export/codegen/sync_datapoint_tags.py --dataset-root ../dataset/codegen
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET_ROOT = SCRIPT_DIR.parents[3].parent / "dataset" / "codegen"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or update codegen datapoint tags from GitHub PR labels.",
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help=f"codegen dataset root (default: {DEFAULT_DATASET_ROOT})",
    )
    parser.add_argument(
        "--instance-id",
        action="append",
        default=[],
        help="limit to one instance_id; can be passed multiple times",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print planned changes without writing files",
    )
    parser.add_argument(
        "--exclude-common",
        action="store_true",
        help="drop common workflow labels such as Review and Verified",
    )
    parser.add_argument(
        "--common-labels",
        type=Path,
        default=SCRIPT_DIR.parents[3] / ".github" / "labels" / "common.json",
        help="common labels JSON used with --exclude-common",
    )
    return parser.parse_args()


def gh_env() -> dict[str, str]:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GH_TOKEN or GITHUB_TOKEN is required", file=sys.stderr)
        sys.exit(1)
    return {**os.environ, "GH_TOKEN": token}


def run_gh_json(args: list[str], *, retries: int = 3) -> Any:
    for attempt in range(retries + 1):
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            env=gh_env(),
        )
        if result.returncode == 0:
            return json.loads(result.stdout or "{}")

        stderr = result.stderr.lower()
        rate_limited = "rate limit" in stderr or "retry-after" in stderr or "429" in stderr
        if rate_limited and attempt < retries:
            wait_seconds = min(60 * (attempt + 1), 300)
            print(f"Rate limited; waiting {wait_seconds}s before retry...", file=sys.stderr)
            time.sleep(wait_seconds)
            continue

        print(result.stderr, file=sys.stderr)
        result.check_returncode()

    raise RuntimeError("unreachable")


def load_json(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    tmp.replace(path)


def normalized_tags(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            parsed = [part.strip() for part in value.split(",") if part.strip()]
        value = parsed
    if not isinstance(value, list):
        value = [value]

    tags: list[str] = []
    seen: set[str] = set()
    for tag in value:
        tag = str(tag)
        if tag and tag not in seen:
            tags.append(tag)
            seen.add(tag)
    return tags


def load_common_labels(path: Path) -> set[str]:
    if not path.exists():
        return set()
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        return set()
    return {
        str(item["name"])
        for item in data
        if isinstance(item, dict) and item.get("name")
    }


def datapoint_paths(dataset_root: Path, instance_ids: set[str]) -> list[Path]:
    paths: list[Path] = []
    for path in dataset_root.rglob("*.json"):
        if path.name.endswith(".tmp"):
            continue
        if path.name == "datapoint.json":
            try:
                data = load_json(path)
            except (json.JSONDecodeError, ValueError):
                continue
            instance_id = str(data.get("instance_id") or path.parent.name)
        else:
            instance_id = path.stem
        if instance_ids and instance_id not in instance_ids:
            continue
        paths.append(path)
    return sorted(paths)


def pr_labels(repo: str, pr_number: int) -> list[str]:
    data = run_gh_json([
        "pr",
        "view",
        str(pr_number),
        "--repo",
        repo,
        "--json",
        "labels",
    ])
    labels = data.get("labels", [])
    return [str(label["name"]) for label in labels if isinstance(label, dict) and label.get("name")]


def sync_path(
    path: Path,
    labels_cache: dict[tuple[str, int], list[str]],
    common_labels: set[str],
    exclude_common: bool,
    dry_run: bool,
) -> tuple[bool, str]:
    data = load_json(path)
    instance_id = str(data.get("instance_id") or path.stem)
    repo = str(data.get("repo") or "")
    pr_number = data.get("pr_number") or data.get("number")
    if not repo or not pr_number:
        return False, f"skip {path}: missing repo or pr_number"

    cache_key = (repo, int(pr_number))
    if cache_key not in labels_cache:
        labels_cache[cache_key] = pr_labels(repo, int(pr_number))

    tags = normalized_tags(labels_cache[cache_key])
    if exclude_common:
        tags = [tag for tag in tags if tag not in common_labels]

    old_tags = normalized_tags(data.get("tags"))
    if "tags" in data and old_tags == tags:
        return False, f"unchanged {instance_id}: {tags}"

    data["tags"] = tags
    if not dry_run:
        write_json(path, data)
    return True, f"{'would update' if dry_run else 'updated'} {path}: {old_tags} -> {tags}"


def main() -> int:
    args = parse_args()
    dataset_root = args.dataset_root.resolve()
    if not dataset_root.is_dir():
        print(f"Error: dataset root does not exist: {dataset_root}", file=sys.stderr)
        return 1

    common_labels = load_common_labels(args.common_labels) if args.exclude_common else set()
    instance_ids = set(args.instance_id)
    paths = datapoint_paths(dataset_root, instance_ids)
    labels_cache: dict[tuple[str, int], list[str]] = {}
    changed = 0

    for path in paths:
        try:
            did_change, message = sync_path(
                path,
                labels_cache,
                common_labels,
                args.exclude_common,
                args.dry_run,
            )
        except Exception as exc:
            print(f"error {path}: {exc}", file=sys.stderr)
            continue
        print(message)
        if did_change:
            changed += 1

    print(f"Processed {len(paths)} files; {'would change' if args.dry_run else 'changed'} {changed}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
