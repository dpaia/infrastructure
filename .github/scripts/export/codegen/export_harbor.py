#!/usr/bin/env python3
"""Export EE-Bench codegen datapoints to Harbor task directories.

Two modes are supported:
  1. Backfill from existing unified datapoints with --from-unified.
  2. Direct PR export using the same --set flags as export_unified.py.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Iterator

from harbor_emitter import emit_harbor_task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


_TEST_FIELD_LINE_RE = re.compile(
    r"^\s*(FAIL_TO_PASS|PASS_TO_PASS)\s*:.*$", re.IGNORECASE | re.MULTILINE
)


def iter_unified_records(
    from_unified: Path,
    *,
    instance_id: str | None = None,
) -> Iterator[tuple[dict, Path | None]]:
    if from_unified.is_file():
        record = _load_json(from_unified)
        if _matches_instance(record, instance_id):
            source_dir = from_unified.parent if from_unified.name == "datapoint.json" else None
            yield record, source_dir
        return

    if not from_unified.is_dir():
        raise FileNotFoundError(f"Unified path does not exist: {from_unified}")

    direct_datapoint = from_unified / "datapoint.json"
    if direct_datapoint.is_file():
        record = _load_json(direct_datapoint)
        if _matches_instance(record, instance_id):
            yield record, from_unified
        return

    for datapoint in sorted(from_unified.rglob("datapoint.json")):
        record = _load_json(datapoint)
        if _matches_instance(record, instance_id):
            yield record, datapoint.parent


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Expected object JSON in {path}")
    return data


def _matches_instance(record: dict, instance_id: str | None) -> bool:
    return instance_id is None or record.get("instance_id") == instance_id


def build_records_from_pr(config: dict[str, str]) -> list[dict]:
    """Run the codegen provider pipeline and return unified records."""

    from ee_bench.dpaia import EEBenchCodegenUnifiedGenerator
    from ee_bench.generator import script_args
    from ee_bench.github import EEBenchEnvironmentProvider, GitHubPullRequestsProvider
    from ee_bench.gradle import GradleProvider
    from ee_bench.maven import MavenProvider
    from ee_bench.metadata import SectionProvider
    from ee_bench.module_test import ModuleTestProvider
    from ee_bench.patch_splitter import PatchSplitterProvider

    # Preserve ee-dataset injected args when this function is run under the runner.
    provider_args = script_args()
    merged_config = {**provider_args, **config}

    repo = merged_config.get("REPO", "dpaia/*")
    version = merged_config.get("VERSION", "1.0")
    limit = int(merged_config.get("LIMIT", "0")) or None
    pr_number = int(merged_config.get("PR_NUMBER", "0")) or None
    data_file = merged_config.get("DATA_FILE", "")
    instance_id_filter = merged_config.get("INSTANCE_ID", "")

    github_token = os.environ["GITHUB_TOKEN"]
    local_data_raw = _load_local_data(data_file)
    local_data_index = _index_local_data(local_data_raw, instance_id_filter)

    def get_local_data(instance_id: str) -> dict:
        if isinstance(local_data_raw, list):
            return local_data_index.get(instance_id, {})
        return local_data_raw

    github = GitHubPullRequestsProvider(token=github_token)
    sections = SectionProvider(
        sections={
            "problem_statement": "## Problem Statement",
            "hints_text": "## Hints",
            "interface": "## Interface",
            "requirements": "## Requirements",
        }
    )
    patch_splitter = PatchSplitterProvider()
    env_provider = EEBenchEnvironmentProvider(
        github_token=github_token,
        benchmark_type="codegen",
    )
    maven = MavenProvider()
    gradle = GradleProvider()
    module_test = ModuleTestProvider()
    codegen = EEBenchCodegenUnifiedGenerator()

    filters = {"repo": repo, "pr_numbers": [pr_number]} if pr_number else None
    records = []

    for item in github.provide(filters=filters, limit=limit):
        preliminary_id = derive_instance_id(item)
        logger.info("Processing %s", preliminary_id)

        local_data = get_local_data(preliminary_id)
        if local_data:
            item.update(local_data)
        normalize_expected_fields(item)

        section_data = sections.provide(text=item["description"])
        if section_data.get("problem_statement"):
            section_data["problem_statement"] = strip_test_field_lines(
                section_data["problem_statement"]
            )
        item["description"] = strip_test_field_lines(item.get("description", ""))

        env_data = env_provider.provide(
            item=item,
            repo_url=item["repo_url"],
            base_commit=item["base_commit"],
            head_commit=item["head_commit"],
        )
        _validate_environment(preliminary_id, env_data)

        instance_id = env_data.get("instance_id") or derive_instance_id(item)
        if instance_id != preliminary_id:
            logger.info("  instance_id overridden by metadata.json: %s", instance_id)

        patch_cls = env_data.pop("patch", None) or {}
        patch_data = patch_splitter.provide(
            patch=item.get("patch", ""),
            exclude_paths=[".ee-bench/"],
            test_patterns=patch_cls.get("test_patterns"),
            source_patterns=patch_cls.get("source_patterns"),
        )

        build_data = (
            maven.provide(
                repo_tree=item.get("repo_tree"),
                test_patch=patch_data.get("test_patch", ""),
            )
            or gradle.provide(
                repo_tree=item.get("repo_tree"),
                test_patch=patch_data.get("test_patch", ""),
            )
            or {}
        )

        test_data = module_test.provide(
            item=item,
            module_map=build_data.get("module_map", {}),
        )

        record = codegen.provide(
            item=item,
            sections=section_data,
            patches=patch_data,
            environment=env_data,
            build=build_data,
            tests=test_data,
            version=version,
            instance_id=instance_id,
        )
        normalize_expected_fields(record)
        records.append(record)

    return records


def _load_local_data(data_file: str) -> dict | list:
    if not data_file:
        return {}
    with open(data_file) as f:
        first_char = f.read(1)
        f.seek(0)
        if first_char == "[":
            return json.load(f)
        return [json.loads(line) for line in f if line.strip()]


def _index_local_data(local_data_raw: dict | list, instance_id_filter: str) -> dict[str, dict]:
    if not isinstance(local_data_raw, list):
        return {}
    result = {}
    for entry in local_data_raw:
        if "instance_id" not in entry:
            continue
        if instance_id_filter and entry["instance_id"] != instance_id_filter:
            continue
        result[entry["instance_id"]] = entry
    return result


def _parse_test_list(value) -> list:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        return [part.strip() for part in value.split(",") if part.strip()]
    return [value]


def normalize_expected_fields(data: dict) -> None:
    expected = data.setdefault("expected", {})
    if not isinstance(expected, dict):
        expected = {}
        data["expected"] = expected

    aliases = {
        "fail_to_pass": ("FAIL_TO_PASS", "fail_to_pass"),
        "pass_to_pass": ("PASS_TO_PASS", "pass_to_pass"),
    }
    for expected_key, source_keys in aliases.items():
        candidates = []
        if expected_key in expected:
            candidates.append(expected[expected_key])
        candidates.extend(
            expected[source_key] for source_key in source_keys if source_key in expected
        )
        candidates.extend(data[source_key] for source_key in source_keys if source_key in data)

        normalized = []
        for candidate in candidates:
            normalized = _parse_test_list(candidate)
            if normalized:
                break
        expected[expected_key] = normalized


def derive_instance_id(item: dict) -> str:
    if item.get("instance_id"):
        return item["instance_id"]
    if item.get("metadata", {}).get("instance_id"):
        return item["metadata"]["instance_id"]
    owner = item.get("owner", "")
    repo = item.get("repo", "")
    number = item.get("number", "unknown")
    full_repo = f"{owner}__{repo}" if owner else repo
    repo_slug = full_repo.replace("-", "__")
    return f"{repo_slug}-{number}"


def strip_test_field_lines(text: str) -> str:
    return _TEST_FIELD_LINE_RE.sub("", text).strip()


def _validate_environment(instance_id: str, env_data: dict) -> None:
    env_files = env_data.get("environment_files", {})
    eval_files = env_data.get("eval", {})
    missing = []
    if not env_files:
        missing.append(".ee-bench directory (no environment files found)")
    elif "Dockerfile" not in env_files:
        missing.append("Dockerfile in .ee-bench/codegen/")
    if "run.sh" not in eval_files:
        missing.append("run.sh in .ee-bench/codegen/eval/")
    if missing:
        raise RuntimeError(
            f"Cannot generate datapoint for {instance_id}: missing {', '.join(missing)}"
        )


def parse_set_flags(pairs: list[str]) -> dict[str, str]:
    result = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Invalid --set value {pair!r}; expected KEY=VALUE")
        key, _, value = pair.partition("=")
        result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-unified",
        type=Path,
        help="Unified instance dir, flat JSON, datapoint.json, or root containing datapoints.",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Set PR export option, compatible with export_unified.py.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory where Harbor task directories are written.",
    )
    parser.add_argument(
        "--instance-id",
        help="Only export this instance id in backfill mode. In PR mode, prefer --set INSTANCE_ID=...",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Fail if an output task directory already exists.",
    )
    args = parser.parse_args()

    exported = []
    try:
        set_config = parse_set_flags(args.set)
        output_dir = args.output_dir or Path(set_config.get("OUTPUT_DIR", "datasets/harbor"))

        if args.from_unified:
            records_with_sources = list(
                iter_unified_records(args.from_unified, instance_id=args.instance_id)
            )
        else:
            records_with_sources = [
                (record, None) for record in build_records_from_pr(set_config)
            ]

        if set_config.get("INSTANCE_ID") and not args.from_unified:
            records_with_sources = [
                (record, source_dir)
                for record, source_dir in records_with_sources
                if record.get("instance_id") == set_config["INSTANCE_ID"]
            ]

        if not records_with_sources:
            target = f" instance_id={args.instance_id!r}" if args.instance_id else ""
            source = args.from_unified or "PR provider pipeline"
            print(f"No datapoints found in {source}{target}", file=sys.stderr)
            return 1

        output_dir.mkdir(parents=True, exist_ok=True)
        for record, source_dir in records_with_sources:
            instance_id = record.get("instance_id")
            if not instance_id:
                raise ValueError("Unified record is missing instance_id")
            task_dir = output_dir / str(instance_id)
            emit_harbor_task(
                record,
                task_dir,
                source_dir=source_dir,
                overwrite=not args.no_overwrite,
            )
            exported.append(task_dir)
            print(f"Exported {instance_id} -> {task_dir}")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Done. {len(exported)} Harbor task(s) exported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
