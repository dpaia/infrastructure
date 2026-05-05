#!/usr/bin/env python3
"""Import SWE-bench Pro datapoints with full .ee-bench/codegen/ structure."""
import json
import logging
import os

from ee_bench.huggingface import HuggingFaceDatasetProvider
from ee_bench.generator import (
    AttachmentFile,
    EEBenchMetadataProvider,
    FileSpec,
    Filter,
    ProjectConfig,
    parse_list_field,
    script_args,
)
from ee_bench.generator.pr_content import PRContentFormatter
from ee_bench.github import GhFileProvider
from ee_bench.github.rate_limit import check_rate_limit, create_github_client
from ee_bench.swe_pro import SweBenchProEvalGenerator
from ee_bench.importer import GitHubPRImporterGenerator
from ee_bench.run_scripts import GitHubAttachmentGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Script args (from --set flags or defaults) ---
args = script_args()
REPO_LANGUAGE = args.get("REPO_LANGUAGE", "")
INSTANCE_ID = args.get("INSTANCE_ID", "")
LIMIT = int(args.get("LIMIT", "0")) or None

# --- Configuration ---
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
HF_TOKEN = os.environ.get("HF_TOKEN", "")
SWE_PRO_OS_PATH = os.environ.get("SWE_PRO_OS_PATH", "")
TARGET_ORG = "dpaia"
DATASET_LABEL = args.get("DATASET_LABEL", "ee-bench-codegen")
STATE_FILE = args.get("STATE_FILE", f".state/{DATASET_LABEL}.json")

# --- Providers ---
hf = HuggingFaceDatasetProvider(
    dataset_name="ScaleAI/SWE-bench_Pro",
    split="test",
    hf_token=HF_TOKEN,
)

swe_files = GhFileProvider(
    repo="scaleapi/SWE-bench_Pro-os",
    github_token=GITHUB_TOKEN,
)

github_client = create_github_client(GITHUB_TOKEN)

swe_import = SweBenchProEvalGenerator()
metadata_gen = EEBenchMetadataProvider()
pr_gen = GitHubPRImporterGenerator()
attach_gen = GitHubAttachmentGenerator()

# --- Clone SWE-bench Pro-os locally (avoids GitHub API calls per file) ---
swe_files.checkout(SWE_PRO_OS_PATH)

# --- Process each item ---
results_import = []
results_attachments = []

filters = []
if INSTANCE_ID:
    filters.append(Filter("instance_id", eq=INSTANCE_ID))
if REPO_LANGUAGE:
    filters.append(Filter("repo_language", eq=REPO_LANGUAGE))

for item in hf.provide(filters=filters, limit=LIMIT):
    instance_id = item["instance_id"]
    logger.info("Processing %s", instance_id)

    # Proactively wait if rate limit is low
    check_rate_limit(github_client)

    # Fetch files from local checkout — paths resolved in Python
    files = swe_files.provide(item, files=[
        FileSpec(path=f"run_scripts/{instance_id}/run_script.sh", field="run_script"),
        FileSpec(path=f"run_scripts/{instance_id}/parser.py", field="parser_script"),
        FileSpec(path=f"dockerfiles/instance_dockerfile/{instance_id}/Dockerfile", field="dockerfile_raw"),
        FileSpec(path=f"dockerfiles/base_dockerfile/{instance_id}/Dockerfile", field="dockerfile_base"),
    ])

    # swe_bench_pro_import -> produces Dockerfile, eval scripts
    repo_name = item["repo"].split("/")[-1]
    import_data = swe_import.provide(
        dockerfile_raw=files.get("dockerfile_raw", ""),
        dockerfile_base=files.get("dockerfile_base", ""),
        run_script=files.get("run_script", ""),
        parser_script=files.get("parser_script", ""),
        target_repo_url=f"https://github.com/{TARGET_ORG}/{repo_name}.git",
        base_commit=item["base_commit"],
        before_repo_set_cmd=item.get("before_repo_set_cmd", ""),
        selected_test_files_to_run=item.get("selected_test_files_to_run", ""),
    )
    # import_data = {"dockerfile": ..., "eval": {...}}

    # metadata_gen -> produces metadata.json with caller-defined structure
    metadata_json = metadata_gen.provide(
        item=item,
        version="1.0",
        instance_id=item.get("instance_id", ""),
        base_commit=item["base_commit"],
        benchmark_type="codegen",
        expected={
            "fail_to_pass": parse_list_field(item.get("fail_to_pass", item.get("FAIL_TO_PASS", ""))),
            "pass_to_pass": parse_list_field(item.get("pass_to_pass", item.get("PASS_TO_PASS", ""))),
        },
        eval={
            "timeout_seconds": 600,
            "selected_test_files_to_run": parse_list_field(
                item.get("selected_test_files_to_run", ""),
            ),
        },
        environment={
            "project_root": "/app",
            "dockerhub_tag": item.get("dockerhub_tag", ""),
            "before_repo_set_cmd": item.get("before_repo_set_cmd", ""),
        },
        fields=[
            "repo",
            "repo_language",
            "issue_specificity",
            "issue_categories",
            "interface",
            "hints_text"
        ],
    )
    import_data["ee_bench.metadata_json"] = metadata_json

    # github_pr_importer -> creates PR in target org
    branch = f"{DATASET_LABEL}/{instance_id}/after"
    formatter = PRContentFormatter()
    problem_statement = item["problem_statement"]
    first_sentence = formatter.format_title(problem_statement)
    pr_body = formatter.format_body(problem_statement, details=[
        ("hints_text", "Hints", item.get("hints_text") or ""),
        ("interface", "Interface", item.get("interface") or ""),
        ("requirements", "Requirements", item.get("requirements") or ""),
    ])

    import_result = pr_gen.provide(
        item=item,
        instance_id=instance_id,
        checksum=item.get("checksum", ""),
        upstream_repo=item["repo"],
        base_commit=item["base_commit"],
        patch=item["patch"],
        test_patch=item.get("test_patch", ""),
        target_org=TARGET_ORG,
        github_token=GITHUB_TOKEN,
        dataset_label=DATASET_LABEL,
        state_file=STATE_FILE,
        head_branch=branch,
        base_branch=f"{DATASET_LABEL}/{instance_id}/before",
        commit_message=f"Import {instance_id}\n\nApply golden patch and test patch from {DATASET_LABEL}",
        pr_title=first_sentence,
        pr_body=pr_body,
        labels=[
            "ee-bench-codegen",
            item["repo_language"],
            *parse_list_field(item.get("issue_categories", "")),
            *parse_list_field(item.get("issue_specificity", "")),
        ],
        repo_topics=[item["repo_language"]],
        projects=[
            ProjectConfig(name="EE Bench"),
            ProjectConfig(name=item["repo_language"]),
        ],
    )
    results_import.extend(import_result)

    # github_attachment -> uploads files to PR branch
    attach_result = attach_gen.provide(
        instance_id=instance_id,
        upstream_repo=item["repo"],
        data=import_data,
        target_org=TARGET_ORG,
        github_token=GITHUB_TOKEN,
        dataset_label=DATASET_LABEL,
        attachment_dir=".ee-bench/codegen",
        branch=branch,
        files=[
            AttachmentFile(path="environment/Dockerfile", field="dockerfile", mode="100644"),
            AttachmentFile(path="metadata.json", field="ee_bench.metadata_json", mode="100644"),
            AttachmentFile(path="eval/*", field="eval", mode="100644"),
            AttachmentFile(path="eval/run.sh", mode="100755"),
            AttachmentFile(path="eval/scripts/run_script.sh", mode="100755"),
        ],
    )
    results_attachments.extend(attach_result)

# --- Write results ---
os.makedirs("results", exist_ok=True)
with open("results/ee-bench-codegen-import.jsonl", "w") as f:
    for record in results_import:
        f.write(json.dumps(record) + "\n")

with open("results/ee-bench-attachments.jsonl", "w") as f:
    for record in results_attachments:
        f.write(json.dumps(record) + "\n")

logger.info("Done. %d imports, %d attachments.", len(results_import), len(results_attachments))
