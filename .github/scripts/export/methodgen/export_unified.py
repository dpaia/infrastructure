#!/usr/bin/env python3
"""Export EE-bench methodgen dataset in unified nested format."""
import json
import logging
import os
import re

from ee_bench.github import GitHubPullRequestsProvider, EEBenchEnvironmentProvider
from ee_bench.generator import Filter, script_args
from ee_bench.metadata import SectionProvider
from ee_bench.patch_splitter import PatchSplitterProvider
from ee_bench.dpaia import EEBenchCodegenUnifiedGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Script args (from --set flags or defaults) ---
args = script_args()
REPO = args.get("REPO", "dpaia/*")
VERSION = args.get("VERSION", "1.0")
LIMIT = int(args.get("LIMIT", "0")) or None
PR_NUMBER = int(args.get("PR_NUMBER", "0")) or None
DATA_FILE = args.get("DATA_FILE", "")
APPEND = args.get("APPEND", "").lower() in ("true", "1", "yes")
INSTANCE_ID = args.get("INSTANCE_ID", "")
OUTPUT_DIR = args.get("OUTPUT_DIR", "")

# Load local data override
local_data_raw: dict | list = {}
if DATA_FILE:
    with open(DATA_FILE) as _f:
        first_char = _f.read(1)
        _f.seek(0)
        if first_char == '[':
            local_data_raw = json.load(_f)
        else:
            local_data_raw = [json.loads(line) for line in _f if line.strip()]

local_data_index: dict[str, dict] = {}
if isinstance(local_data_raw, list):
    for entry in local_data_raw:
        if "instance_id" in entry:
            if INSTANCE_ID and entry["instance_id"] != INSTANCE_ID:
                continue
            local_data_index[entry["instance_id"]] = entry
else:
    local_data_index = {}

def get_local_data(instance_id: str) -> dict:
    if isinstance(local_data_raw, list):
        return local_data_index.get(instance_id, {})
    return local_data_raw


# --- Configuration ---
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

# --- Providers ---
github = GitHubPullRequestsProvider(token=GITHUB_TOKEN)

sections = SectionProvider(sections={
    "problem_statement": "## Problem Statement",
    "hints_text": "## Hints",
})

patch_splitter = PatchSplitterProvider()

env_provider = EEBenchEnvironmentProvider(
    github_token=GITHUB_TOKEN,
    benchmark_type="methodgen",
)

generator = EEBenchCodegenUnifiedGenerator()


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


def write_instance_dir(record: dict, output_base: str = "") -> None:
    """Write per-instance directory with unpacked artifacts and a datapoint.json."""
    iid = record["instance_id"]
    root = output_base or "datasets/unified"
    base = f"{root}/{iid}"
    os.makedirs(base, exist_ok=True)

    dp = dict(record)

    # environment/ — Dockerfile + build context files
    os.makedirs(f"{base}/environment", exist_ok=True)
    env_section = record.get("environment", {})
    dp_env_files = {}
    for name, content in env_section.get("files", {}).items():
        path = f"{base}/environment/{name}"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        dp_env_files[name] = f"environment/{name}"
    dp["environment"] = {"files": dp_env_files}
    for k, v in env_section.items():
        if k != "files":
            dp["environment"][k] = v

    # eval/ — run.sh, scripts/, config/
    os.makedirs(f"{base}/eval", exist_ok=True)
    eval_section = record.get("eval", {})
    dp_eval_files = {}
    for name, content in eval_section.get("files", {}).items():
        path = f"{base}/eval/{name}"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        dp_eval_files[name] = f"eval/{name}"
    dp["eval"] = {"files": dp_eval_files}

    # verify/ — patch.diff
    os.makedirs(f"{base}/verify", exist_ok=True)
    verify_section = record.get("verify", {})
    dp_verify_files = {}
    for name, content in verify_section.get("files", {}).items():
        path = f"{base}/verify/{name}"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        dp_verify_files[name] = f"verify/{name}"
    dp["verify"] = {"files": dp_verify_files}

    # datapoint.json
    with open(f"{base}/datapoint.json", "w") as f:
        json.dump(dp, f, indent=2)


# --- Process each PR ---
records = []

if PR_NUMBER:
    filters = {"repo": REPO, "pr_numbers": [PR_NUMBER]}
else:
    filters = None

for item in github.provide(filters=filters, limit=LIMIT):
    preliminary_id = derive_instance_id(item)
    logger.info("Processing %s", preliminary_id)

    local_data = get_local_data(preliminary_id)
    if local_data:
        item.update(local_data)

    section_data = sections.provide(text=item["description"])

    # Resolve .ee-bench/methodgen/ files
    env_data = env_provider.provide(
        item=item,
        repo_url=item["repo_url"],
        base_commit=item["base_commit"],
        head_commit=item["head_commit"],
    )

    env_files = env_data.get("environment_files", {})
    eval_files = env_data.get("eval", {})
    missing = []
    if not env_files:
        missing.append(".ee-bench directory (no environment files found)")
    elif "Dockerfile" not in env_files:
        missing.append("Dockerfile in .ee-bench/methodgen/")
    if "run.sh" not in eval_files:
        missing.append("run.sh in .ee-bench/methodgen/eval/")
    if missing:
        raise RuntimeError(
            f"Cannot generate datapoint for {preliminary_id}: missing {', '.join(missing)}"
        )

    instance_id = env_data.get("instance_id") or derive_instance_id(item)
    if instance_id != preliminary_id:
        logger.info("  instance_id overridden by metadata.json: %s", instance_id)

    # Split patch (exclude .ee-bench/ infrastructure files)
    patch_cls = env_data.get("patch") or {}
    patch_data = patch_splitter.provide(
        patch=item.get("patch", ""),
        exclude_paths=[".ee-bench/"],
        test_patterns=patch_cls.get("test_patterns"),
        source_patterns=patch_cls.get("source_patterns"),
    )

    # Generate unified nested record
    record = generator.provide(
        item=item,
        sections=section_data,
        patches=patch_data,
        environment=env_data,
        version=VERSION,
        instance_id=instance_id,
    )
    records.append(record)

# --- Write output ---
_output_root = OUTPUT_DIR or "datasets"
os.makedirs(_output_root, exist_ok=True)

for record in records:
    flat_path = os.path.join(_output_root, f"{record['instance_id']}.json")
    with open(flat_path, "w") as f:
        json.dump(record, f, indent=2)
    logger.info("Wrote flat JSON: %s", flat_path)

_instance_dir_root = OUTPUT_DIR or ""
for record in records:
    write_instance_dir(record, output_base=_instance_dir_root)

logger.info("Done. %d records exported.", len(records))
