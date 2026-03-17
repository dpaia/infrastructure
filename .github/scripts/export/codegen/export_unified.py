#!/usr/bin/env python3
"""Export EE-bench codegen dataset in unified nested format."""
import json
import logging
import os
import re

from ee_bench.github import GitHubPullRequestsProvider, EEBenchEnvironmentProvider
from ee_bench.generator import Filter, script_args
from ee_bench.metadata import SectionProvider
from ee_bench.patch_splitter import PatchSplitterProvider
from ee_bench.maven import MavenProvider
from ee_bench.gradle import GradleProvider
from ee_bench.module_test import ModuleTestProvider
from ee_bench.dpaia import EEBenchCodegenUnifiedGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Script args (from --set flags or defaults) ---
args = script_args()
REPO = args.get("REPO", "dpaia/*")
VERSION = args.get("VERSION", "1.0")
LIMIT = int(args.get("LIMIT", "0")) or None
PR_NUMBER = int(args.get("PR_NUMBER", "0")) or None
DATA_FILE = args.get("DATA_FILE", "")  # Local JSON/JSONL to merge authoritative fields
APPEND = args.get("APPEND", "").lower() in ("true", "1", "yes")
INSTANCE_ID = args.get("INSTANCE_ID", "")
OUTPUT_DIR = args.get("OUTPUT_DIR", "")

# Load local data override (base_commit, FAIL_TO_PASS, patch, test_patch, etc.)
# If the file contains a JSON array, build a lookup dict keyed by instance_id.
local_data_raw: dict | list = {}
if DATA_FILE:
    with open(DATA_FILE) as _f:
        first_char = _f.read(1)
        _f.seek(0)
        if first_char == '[':
            local_data_raw = json.load(_f)
        else:
            # JSONL format
            local_data_raw = [json.loads(line) for line in _f if line.strip()]

local_data_index: dict[str, dict] = {}
if isinstance(local_data_raw, list):
    for entry in local_data_raw:
        if "instance_id" in entry:
            if INSTANCE_ID and entry["instance_id"] != INSTANCE_ID:
                continue
            local_data_index[entry["instance_id"]] = entry
else:
    local_data_index = {}  # handled per-item below

def get_local_data(instance_id: str) -> dict:
    if isinstance(local_data_raw, list):
        return local_data_index.get(instance_id, {})
    return local_data_raw  # plain dict applies to all items

# --- Configuration ---
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

# --- Providers ---
github = GitHubPullRequestsProvider(token=GITHUB_TOKEN)

sections = SectionProvider(sections={
    "problem_statement": "## Problem Statement",
    "requirements": "## Requirements",
    "hints_text": "## Hints",
    "interface": "## Interface"
})

patch_splitter = PatchSplitterProvider()

env_provider = EEBenchEnvironmentProvider(
    github_token=GITHUB_TOKEN,
    benchmark_type="codegen",
)

maven = MavenProvider()
gradle = GradleProvider()
module_test = ModuleTestProvider()

codegen = EEBenchCodegenUnifiedGenerator()

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


_TEST_FIELD_LINE_RE = re.compile(
    r"^\s*(FAIL_TO_PASS|PASS_TO_PASS)\s*:.*$", re.IGNORECASE | re.MULTILINE
)

def strip_test_field_lines(text: str) -> str:
    """Remove FAIL_TO_PASS: and PASS_TO_PASS: lines from text."""
    return _TEST_FIELD_LINE_RE.sub("", text).strip()


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
    # Preserve non-file keys (e.g. docker_run_params)
    for k, v in env_section.items():
        if k != "files":
            dp["environment"][k] = v

    # eval/ — run.sh, scripts/, test_patch.diff
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

    # datapoint.json — record with relative file paths
    with open(f"{base}/datapoint.json", "w") as f:
        json.dump(dp, f, indent=2)


# --- Process each PR ---
records = []

if PR_NUMBER:
    filters = {"repo": REPO, "pr_numbers": [PR_NUMBER]}
else:
    filters = None

for item in github.provide(filters=filters, limit=LIMIT):
    # Derive a preliminary instance_id for logging and local_data lookup
    preliminary_id = derive_instance_id(item)
    logger.info("Processing %s", preliminary_id)

    # Merge authoritative fields from local data file (overrides PR-derived values)
    local_data = get_local_data(preliminary_id)
    if local_data:
        item.update(local_data)

    # Enrich: extract markdown sections from PR body
    section_data = sections.provide(text=item["description"])
    if section_data.get("problem_statement"):
        section_data["problem_statement"] = strip_test_field_lines(section_data["problem_statement"])
    item["description"] = strip_test_field_lines(item.get("description", ""))

    # Enrich: resolve .ee-bench/codegen/ files (Dockerfile, eval/, metadata.json)
    # Must run before patch_splitter so metadata.json patch classification is available.
    env_data = env_provider.provide(
        item=item,
        repo_url=item["repo_url"],
        base_commit=item["base_commit"],
        head_commit=item["head_commit"],
    )

    # Use instance_id from metadata.json (via env_data) if available,
    # falling back to the PR-derived value.
    instance_id = env_data.get("instance_id") or derive_instance_id(item)
    if instance_id != preliminary_id:
        logger.info("  instance_id overridden by metadata.json: %s", instance_id)

    # Enrich: split patch into source + test (exclude .ee-bench/ infrastructure files)
    # Use metadata.json patch classification patterns if available.
    patch_cls = env_data.get("patch") or {}
    patch_data = patch_splitter.provide(
        patch=item.get("patch", ""),
        exclude_paths=[".ee-bench/"],
        test_patterns=patch_cls.get("test_patterns"),
        source_patterns=patch_cls.get("source_patterns"),
    )

    # Enrich: detect build system
    build_data = (
        maven.provide(repo_tree=item.get("repo_tree"), test_patch=patch_data.get("test_patch", ""))
        or gradle.provide(repo_tree=item.get("repo_tree"), test_patch=patch_data.get("test_patch", ""))
        or {}
    )

    # FAIL_TO_PASS: check all sources, skip empty strings like "[]"
    def _non_empty(val):
        """True if val is a non-trivial value (not None, not empty, not '[]')."""
        if val is None:
            return False
        if isinstance(val, str):
            stripped = val.strip()
            return stripped not in ("", "[]", "null")
        if isinstance(val, list):
            return len(val) > 0
        return bool(val)

    _ftp_candidates = [
        item.get("FAIL_TO_PASS"), item.get("fail_to_pass"),
        env_data.get("FAIL_TO_PASS"), env_data.get("fail_to_pass"),
    ]
    fail_to_pass = next((v for v in _ftp_candidates if _non_empty(v)), [])

    _ptp_candidates = [
        item.get("PASS_TO_PASS"), item.get("pass_to_pass"),
        env_data.get("PASS_TO_PASS"), env_data.get("pass_to_pass"),
    ]
    pass_to_pass = next((v for v in _ptp_candidates if _non_empty(v)), [])

    # Enrich: add module prefixes to test names if needed
    test_data = module_test.provide(
        item=item,
        module_map=build_data.get("module_map", {}),
        FAIL_TO_PASS=fail_to_pass,
        PASS_TO_PASS=pass_to_pass,
    )
    logger.info("  test_data: %s", {k: v for k, v in test_data.items() if 'FAIL' in k or 'PASS' in k})

    # Generate: structure into unified nested record
    record = codegen.provide(
        item=item,
        sections=section_data,
        patches=patch_data,
        environment=env_data,
        build=build_data,
        tests=test_data,
        version=VERSION,
        instance_id=instance_id,
    )
    records.append(record)

# --- Write output ---
_output_root = OUTPUT_DIR or "datasets"
os.makedirs(_output_root, exist_ok=True)

# 1. Self-contained flat JSON per instance (all files inlined)
for record in records:
    flat_path = os.path.join(_output_root, f"{record['instance_id']}.json")
    with open(flat_path, "w") as f:
        json.dump(record, f, indent=2)
    logger.info("Wrote flat JSON: %s", flat_path)

# 2. Per-instance directories with unpacked artifacts
_instance_dir_root = OUTPUT_DIR or ""
for record in records:
    write_instance_dir(record, output_base=_instance_dir_root)

logger.info("Done. %d records exported.", len(records))
