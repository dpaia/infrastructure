#!/usr/bin/env python3
"""Resolve instance IDs for dataset export.

With --query: searches project board via GitHub API, fetches Data field URLs,
resolves to local paths in the dataset checkout.
Without --query: scans the dataset directory for all datapoint.json files.

Prerequisites:
    - GH_TOKEN env var set (e.g. `export GH_TOKEN=$(gh auth token)`)
    - Dataset repo cloned locally (e.g. `git clone https://github.com/dpaia/dataset.git dataset-checkout`)

Usage:
    # Filter by board query (e.g. all C# datapoints):
    PYTHONPATH=.github/scripts/export python .github/scripts/export/resolve_instances_v2.py \\
        --query 'label:"Language: C#"' \\
        --eval-type codegen \\
        --dataset-dir ./dataset-checkout \\
        --output ./instance-ids.txt

    # Export all datapoints (no query):
    PYTHONPATH=.github/scripts/export python .github/scripts/export/resolve_instances_v2.py \\
        --eval-type codegen \\
        --dataset-dir ./dataset-checkout \\
        --output ./instance-ids.txt
"""

import argparse
import json
import os
import sys
from pathlib import Path

from github_client_v2 import (
    download_content,
    fetch_data_field_urls,
    parse_data_url,
    search_board_items,
)


def resolve_from_query(
    query: str,
    eval_type: str,
    org: str,
    project_number: int,
    metadata_project_number: int,
    dataset_dir: Path,
) -> list[str]:
    """Resolve instance IDs by searching the project board.

    Searches project_number (board with labels) for matching PRs,
    then fetches Data field URLs from metadata_project_number (Dataset Metadata project).
    """

    # Step 1: Search board for matching PRs
    print(f"Searching project board {org}/{project_number} with query: {query}")
    items = search_board_items(org, project_number, query)
    print(f"Found {len(items)} matching items on board")

    if not items:
        return []

    # Step 2: Batch-fetch Data field URLs from metadata project via GraphQL
    node_ids = [item["node_id"] for item in items]
    print(f"Fetching Data field values from metadata project {org}/{metadata_project_number} for {len(node_ids)} items...")
    data_urls = fetch_data_field_urls(org, metadata_project_number, node_ids)
    print(f"Got {len(data_urls)} Data field URLs")

    # Step 3: Parse URLs and resolve to local paths
    instance_ids = []
    fallback_needed = []

    for item in items:
        node_id = item["node_id"]
        url = data_urls.get(node_id)

        if not url:
            print(f"  Warning: no Data field for {item['repo_name']}#{item['number']}", file=sys.stderr)
            continue

        parsed = parse_data_url(url)
        if not parsed:
            print(f"  Warning: could not parse URL: {url}", file=sys.stderr)
            continue

        instance_id = parsed["instance_id"]

        # Try local lookup first
        local_dir = dataset_dir / parsed["dir_path"]
        local_json = dataset_dir / parsed["file_path"]

        if local_dir.is_dir():
            instance_ids.append(instance_id)
            print(f"  Local: {instance_id}")
        elif local_json.is_file():
            instance_ids.append(instance_id)
            print(f"  Local (json): {instance_id}")
        else:
            fallback_needed.append((item, parsed))

    # Step 4: Download fallback for items not found locally
    if fallback_needed:
        print(f"\n{len(fallback_needed)} items not found locally, attempting API download...")
        for item, parsed in fallback_needed:
            print(f"  Downloading: {parsed['owner']}/{parsed['repo']}/{parsed['file_path']}")
            content = download_content(
                parsed["owner"], parsed["repo"], parsed["branch"], parsed["file_path"]
            )
            if content:
                # Save downloaded content to dataset dir
                target_json = dataset_dir / parsed["file_path"]
                target_dir = dataset_dir / parsed["dir_path"]
                target_dir.mkdir(parents=True, exist_ok=True)
                target_json.parent.mkdir(parents=True, exist_ok=True)

                # Write datapoint.json inside the instance directory
                datapoint_path = target_dir / "datapoint.json"
                datapoint_path.write_text(content)
                instance_ids.append(parsed["instance_id"])
                print(f"  Downloaded: {parsed['instance_id']}")
            else:
                print(f"  Failed: {item['repo_name']}#{item['number']}", file=sys.stderr)

    return sorted(set(instance_ids))


def resolve_from_filesystem(eval_type: str, dataset_dir: Path) -> list[str]:
    """Resolve all instance IDs from the dataset directory."""
    print(f"Collecting all instances from filesystem")

    instance_ids = set()
    if eval_type == "all":
        search_root = dataset_dir
    else:
        search_root = dataset_dir / eval_type

    if not search_root.is_dir():
        print(f"Warning: directory not found: {search_root}", file=sys.stderr)
        return []

    for datapoint in search_root.rglob("datapoint.json"):
        instance_ids.add(datapoint.parent.name)

    result = sorted(instance_ids)
    print(f"Found {len(result)} instance IDs from filesystem")
    return result


def main():
    parser = argparse.ArgumentParser(description="Resolve instance IDs for dataset export")
    parser.add_argument("--query", default="", help="GitHub search query for project board items")
    parser.add_argument("--eval-type", default="codegen", help="Eval type directory (codegen, debugging, or all)")
    parser.add_argument("--org", default="dpaia", help="GitHub organization")
    parser.add_argument("--project-number", type=int, default=13, help="Project board number (for search)")
    parser.add_argument("--metadata-project-number", type=int, default=3, help="Dataset Metadata project number (for Data field)")
    parser.add_argument("--dataset-dir", required=True, help="Path to dataset checkout directory")
    parser.add_argument("--output", required=True, help="Output file for instance IDs (one per line)")

    args = parser.parse_args()
    dataset_dir = Path(args.dataset_dir)

    if not dataset_dir.is_dir():
        print(f"Error: dataset directory not found: {dataset_dir}", file=sys.stderr)
        sys.exit(1)

    if args.query:
        instance_ids = resolve_from_query(
            query=args.query,
            eval_type=args.eval_type,
            org=args.org,
            project_number=args.project_number,
            metadata_project_number=args.metadata_project_number,
            dataset_dir=dataset_dir,
        )
    else:
        instance_ids = resolve_from_filesystem(args.eval_type, dataset_dir)

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(instance_ids) + "\n" if instance_ids else "")

    print(f"\nTotal instance IDs to export: {len(instance_ids)}")
    print(f"Written to: {output_path}")


if __name__ == "__main__":
    main()