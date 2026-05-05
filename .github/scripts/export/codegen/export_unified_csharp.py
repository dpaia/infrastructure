#!/usr/bin/env python3
"""Import C# datapoints from local JSONL with two-pass approach.

Pass 1: Push shared configs (Dockerfile, parser, latest install/test scripts)
        to the main branch of each dpaia fork.
Pass 2: Create PRs with per-instance eval artifacts.

Uses local git operations (clone/branch/commit/push) instead of GitHub API
for all git work, reducing API calls from ~20-25 to ~5 per instance.
"""
import json
import logging
import os
import random
import time
from collections import defaultdict
from pathlib import Path

from github import Github, GithubException

from ee_bench.generator import (
    EEBenchMetadataProvider,
    ProjectConfig,
    parse_list_field,
    script_args,
)
from ee_bench.generator.pr_content import PRContentFormatter
from ee_bench.github.rate_limit import check_rate_limit, create_github_client, retry_on_rate_limit
from ee_bench.csharp import CSharpEvalGenerator
from ee_bench.git import LocalGitConfigurer, PatchApplier
from ee_bench.importer.sync_state import (
    check_sync_status,
    load_state,
    save_state,
    update_item_state,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _random_color() -> str:
    """Generate a random 6-digit hex color string."""
    return f"{random.randint(0, 0xFFFFFF):06x}"


def ensure_fork(gh: Github, upstream_repo: str, target_org: str) -> str:
    """Ensure a fork exists in target_org. Creates it if missing. Returns fork full_name."""
    repo_name = upstream_repo.split("/")[-1]
    fork_full = f"{target_org}/{repo_name}"
    try:
        gh.get_repo(fork_full)
        logger.info("Fork already exists: %s", fork_full)
        return fork_full
    except GithubException as e:
        if e.status != 404:
            raise

    logger.info("Creating fork %s from %s", fork_full, upstream_repo)
    source = gh.get_repo(upstream_repo)
    org = gh.get_organization(target_org)
    org.create_fork(source)
    # Wait for fork to become available
    for attempt in range(30):
        time.sleep(2)
        try:
            gh.get_repo(fork_full)
            logger.info("Fork ready: %s", fork_full)
            return fork_full
        except GithubException:
            pass
    raise RuntimeError(f"Fork {fork_full} not available after 60s")


def ensure_labels(repo, label_names: list[str], label_cache: dict[str, set[str]]) -> None:
    """Ensure labels exist on a GitHub repo, creating if needed."""
    repo_key = repo.full_name
    if repo_key not in label_cache:
        label_cache[repo_key] = {label.name for label in repo.get_labels()}
    for name in label_names:
        if name not in label_cache[repo_key]:
            try:
                repo.create_label(name=name, color=_random_color())
                label_cache[repo_key].add(name)
            except Exception:
                label_cache[repo_key].add(name)


def write_file(path: Path, content: str, *, executable: bool = False) -> None:
    """Write content to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if executable:
        path.chmod(0o755)


# --- Script args (from --set flags or defaults) ---
args = script_args()
INSTANCE_ID = args.get("INSTANCE_ID", "")
LIMIT = int(args.get("LIMIT", "0")) or None
DATASET_LABEL = args.get("DATASET_LABEL", "ee-bench-csharp")
STATE_FILE = args.get("STATE_FILE", f".state/{DATASET_LABEL}.json")
CHECKOUT_DIR = args.get("CHECKOUT_DIR", ".checkouts")
VALIDATED_FILE = args.get("VALIDATED_FILE", "")  # Progress file with validated instance_ids
FORCE_SHARED = args.get("FORCE_SHARED", "").lower() in ("true", "1", "yes")  # Force overwrite .ee-bench on main

# --- Configuration ---
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
CSHARP_HARNESS_PATH = os.environ.get("CSHARP_HARNESS_PATH", "/Users/Evgenii.Zakharchenko/IdeaProjects/LLM/evaluation/swebench_matterhorn/benchmarks")
TARGET_ORG = "dpaia"
DATASET_FILE = args.get("DATASET_FILE", "datasets/csharp-instances.jsonl")

# --- Providers ---
csharp_gen = CSharpEvalGenerator()
metadata_gen = EEBenchMetadataProvider()
git_cfg = LocalGitConfigurer(base_dir=CHECKOUT_DIR)
patcher = PatchApplier()

# --- Load dataset ---
items: list[dict] = []
with open(DATASET_FILE) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        if INSTANCE_ID and item["instance_id"] != INSTANCE_ID:
            continue
        items.append(item)
        if LIMIT and len(items) >= LIMIT:
            break

logger.info("Loaded %d instances from %s", len(items), DATASET_FILE)

# --- Load Dockerfiles from CSHARP_HARNESS_PATH ---
dockerfiles: dict[str, str] = {}
if CSHARP_HARNESS_PATH:
    docker_dir = Path(CSHARP_HARNESS_PATH) / "dockerfiles" / "csharp-swe-bench"
    if docker_dir.is_dir():
        for item in items:
            tag = item["dockerfile_tag"]
            if tag not in dockerfiles:
                dfile = docker_dir / f"{tag}.dockerfile"
                if dfile.exists():
                    dockerfiles[tag] = dfile.read_text()
                    logger.info("Loaded Dockerfile for tag %s", tag)
                else:
                    logger.warning("Dockerfile not found: %s", dfile)
    else:
        logger.warning("Docker dir not found: %s", docker_dir)
else:
    logger.warning("CSHARP_HARNESS_PATH not set — Dockerfiles will be empty")


# --- GitHub client (needed for fork creation and PR operations) ---
from ee_bench.github.project_manager import ProjectManager

github_client = create_github_client(GITHUB_TOKEN)
project_manager = ProjectManager(github_client)
label_cache: dict[str, set[str]] = {}

# --- Load validated instance_ids (for Pass 1 skip logic) ---
validated_ids: set[str] = set()
if VALIDATED_FILE and os.path.exists(VALIDATED_FILE):
    with open(VALIDATED_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                validated_ids.add(line)

# --- Group items by repo for Pass 1 ---
repo_items: dict[str, list[dict]] = defaultdict(list)
for item in items:
    repo_items[item["repo"]].append(item)


# ============================================================
# Pass 1: Push shared configs to main branch of each dpaia fork
# ============================================================
logger.info("=== Pass 1: Repo setup (%d repos) ===", len(repo_items))

for repo, repo_instances in repo_items.items():
    repo_name = repo.split("/")[-1]
    representative = repo_instances[0]
    dockerfile_content = dockerfiles.get(representative["dockerfile_tag"], "")

    # Generate shared artifacts using a representative instance
    gen_result = csharp_gen.provide(
        repo=repo,
        dockerfile_content=dockerfile_content,
        base_commit=representative["base_commit"],
        test_framework=representative.get("test_framework") or "",
        env_setup_version=representative["env_setup_version"],
        run_tests_version=representative["run_tests_version"],
        target_org=TARGET_ORG,
    )

    repo_shared = gen_result["repo_shared"]

    # Ensure fork exists, then clone and checkout main
    ensure_fork(github_client, repo, TARGET_ORG)
    checkout = git_cfg.provide(
        fork_repo=f"{TARGET_ORG}/{repo_name}",
        upstream_repo=repo,
    )
    clone_dir = checkout["clone_dir"]
    default_branch = git_cfg.default_branch(clone_dir)
    git_cfg.checkout(clone_dir, default_branch)

    # Skip shared config push if .ee-bench exists AND at least one instance
    # for this repo has already been validated. If no instances are validated,
    # overwrite — the existing files may be from a failed attempt.
    ee_bench_dir = clone_dir / ".ee-bench"
    repo_instance_ids = {inst["instance_id"] for inst in repo_instances}
    has_validated = bool(repo_instance_ids & validated_ids)

    if ee_bench_dir.exists() and has_validated and not FORCE_SHARED:
        logger.info("Repo setup %s: .ee-bench exists and has validated instances, skipping", repo_name)
    else:
        if FORCE_SHARED:
            logger.info("Repo setup %s: FORCE_SHARED=true, overwriting .ee-bench", repo_name)
        elif ee_bench_dir.exists():
            logger.info("Repo setup %s: .ee-bench exists but no validated instances, overwriting", repo_name)

        # Write shared files directly to worktree
        for path, content in repo_shared.items():
            full_path = clone_dir / ".ee-bench" / "codegen" / path
            is_executable = path.endswith(".sh")
            write_file(full_path, content, executable=is_executable)

        try:
            git_cfg.commit(clone_dir, [".ee-bench/"], "Update shared configs", force=True)
            git_cfg.push(clone_dir, [default_branch])
            logger.info("Repo setup %s: pushed shared configs", repo_name)
        except Exception as e:
            logger.warning("Repo setup %s: %s", repo_name, e)


# ============================================================
# Pass 2: Per-instance PRs
# ============================================================
logger.info("=== Pass 2: Per-instance import (%d instances) ===", len(items))

results_import = []

# Load state for idempotent re-runs
state = load_state(STATE_FILE)
state.dataset = DATASET_LABEL

for item in items:
    instance_id = item["instance_id"]
    repo = item["repo"]
    repo_name = repo.split("/")[-1]
    fork_repo_name = f"{TARGET_ORG}/{repo_name}"
    logger.info("Processing %s", instance_id)

    # Proactively wait if rate limit is low before making API calls
    check_rate_limit(github_client)

    # Check sync state
    checksum = item.get("checksum", instance_id)
    sync_status = check_sync_status(state, instance_id, checksum)
    if sync_status == "skip":
        logger.info("Skipping %s (unchanged)", instance_id)
        results_import.append({
            "instance_id": instance_id,
            "status": "skipped",
            "pr_url": state.items[instance_id].pr_url,
            "pr_number": state.items[instance_id].pr_number,
            "fork_repo": state.items[instance_id].fork_repo,
            "error": "",
        })
        continue

    dockerfile_content = dockerfiles.get(item["dockerfile_tag"], "")

    # Generate per-instance eval files (for metadata.json inline)
    gen_result = csharp_gen.provide(
        repo=repo,
        dockerfile_content=dockerfile_content,
        base_commit=item["base_commit"],
        test_framework=item.get("test_framework") or "",
        env_setup_version=item["env_setup_version"],
        run_tests_version=item["run_tests_version"],
        target_org=TARGET_ORG,
    )

    # Build metadata.json with eval_files inline
    metadata_json = metadata_gen.provide(
        item=item,
        instance_id=instance_id,
        base_commit=item["base_commit"],
        benchmark_type="codegen",
        expected={
            "fail_to_pass": parse_list_field(item.get("FAIL_TO_PASS", "")),
            "pass_to_pass": parse_list_field(item.get("PASS_TO_PASS", "")),
        },
        eval={
            "test_framework": item.get("test_framework") or "",
            "env_setup_version": item["env_setup_version"],
            "run_tests_version": item["run_tests_version"],
            "files": gen_result["eval_files"],
        },
        environment={
            "project_root": "/app",
            "dockerfile_tag": item["dockerfile_tag"],
        },
        language="csharp",
        env_setup_version=item["env_setup_version"],
        run_tests_version=item["run_tests_version"],
        test_framework=item.get("test_framework") or "",
        test_framework_flag=f"--framework {item['test_framework']}" if item.get("test_framework") else "",
        test_project=gen_result["test_project"],
        test_logger=gen_result["test_logger"],
        build_flags=gen_result.get("build_flags", ""),
        execution_flags=item.get("execution_flags") or "",
        fields=[
            "repo",
        ],
    )

    base_branch = f"{DATASET_LABEL}/{instance_id}/before"
    head_branch = f"{DATASET_LABEL}/{instance_id}/after"

    try:
        # A: Clone/reuse and set up branches
        checkout = git_cfg.provide(
            fork_repo=fork_repo_name,
            upstream_repo=repo,
        )
        clone_dir = checkout["clone_dir"]

        git_cfg.fetch_commit(clone_dir, item["base_commit"])
        git_cfg.create_branch(clone_dir, base_branch, item["base_commit"])
        git_cfg.create_branch(clone_dir, head_branch, item["base_commit"])
        git_cfg.checkout(clone_dir, head_branch)

        # B: Apply patches
        patcher.provide(
            clone_dir=clone_dir,
            patch=item["patch"],
            test_patch=item.get("test_patch", ""),
        )
        git_cfg.commit(
            clone_dir, ["."],
            f"Import {instance_id}\n\nApply patches from {DATASET_LABEL}",
        )

        # C: Write .ee-bench/codegen/metadata.json to worktree
        #    (Dockerfile, run.sh, parser.py are Jinja2 templates on main;
        #     install.sh, run_script.sh are inline in metadata.json evaluation.files)
        ee_bench_dir = clone_dir / ".ee-bench" / "codegen"
        write_file(ee_bench_dir / "metadata.json", metadata_json)

        git_cfg.commit(
            clone_dir, [".ee-bench/"],
            f"Add .ee-bench files for {instance_id}",
            force=True,
        )

        # D: Find existing PR and reopen BEFORE force-pushing branches.
        #    GitHub rejects reopening a closed PR whose branch was force-pushed,
        #    so we must reopen while the old branch state still matches.
        fork = retry_on_rate_limit(github_client.get_repo, fork_repo_name)

        existing_prs = list(retry_on_rate_limit(
            fork.get_pulls,
            state="all", head=f"{TARGET_ORG}:{head_branch}", base=base_branch,
        ))
        existing_pr = None
        if existing_prs:
            existing_pr = existing_prs[0]
            if existing_pr.state == "closed":
                retry_on_rate_limit(existing_pr.edit, state="open")
                logger.info("Reopened closed PR #%d for %s", existing_pr.number, instance_id)

        # E: Push both branches (force-push is safe now — PR is open or new)
        git_cfg.push(clone_dir, [base_branch, head_branch], force=True)

        # F: Create or update PR
        formatter = PRContentFormatter()
        problem_statement = item.get("problem_statement", "")
        first_sentence = formatter.format_title(problem_statement)
        pr_body = formatter.format_body(problem_statement, details=[
            ("hints_text", "Hints", item.get("hints_text") or ""),
            ("interface", "Interface", item.get("interface") or ""),
            ("requirements", "Requirements", item.get("requirements") or ""),
        ])

        if existing_pr:
            retry_on_rate_limit(existing_pr.edit, title=first_sentence, body=pr_body)
            pr = existing_pr
            result_status = "updated"
            logger.info("Updated existing PR #%d for %s", pr.number, instance_id)
        else:
            pr = retry_on_rate_limit(
                fork.create_pull,
                title=first_sentence,
                body=pr_body,
                head=head_branch,
                base=base_branch,
            )
            result_status = "created"

        labels = [
            "Language: C#",
            *(["test_framework:" + item["test_framework"]] if item.get("test_framework") else []),
        ]
        ensure_labels(fork, labels, label_cache)
        pr.add_to_labels(*labels)

        # Add to projects
        for proj in [ProjectConfig(name="EE Bench"), ProjectConfig(name="Code Generation")]:
            try:
                project_id = project_manager.ensure_project(TARGET_ORG, proj.name)
                pr_node_id = pr.raw_data.get("node_id", "")
                if pr_node_id:
                    project_manager.add_pr_to_project(project_id, pr_node_id)
            except Exception as e:
                logger.warning("Failed to add PR to project '%s': %s", proj.name, e)

        result = {
            "instance_id": instance_id,
            "status": result_status,
            "pr_url": pr.html_url,
            "pr_number": pr.number,
            "fork_repo": fork_repo_name,
            "error": "",
        }
        results_import.append(result)

        # F: Update state
        update_item_state(
            state, instance_id,
            checksum=checksum,
            pr_number=pr.number,
            pr_url=pr.html_url,
            fork_repo=fork_repo_name,
            status=result_status,
        )
        save_state(state, STATE_FILE)

    except Exception as e:
        logger.error("Failed to import %s: %s", instance_id, e)
        results_import.append({
            "instance_id": instance_id,
            "status": "error",
            "pr_url": "",
            "pr_number": None,
            "fork_repo": fork_repo_name,
            "error": str(e),
        })
        update_item_state(
            state, instance_id,
            checksum=checksum,
            status="error",
        )
        save_state(state, STATE_FILE)

# --- Write results ---
os.makedirs("results", exist_ok=True)
with open("results/ee-bench-csharp-import.jsonl", "w") as f:
    for record in results_import:
        f.write(json.dumps(record) + "\n")

logger.info("Done. %d imports.", len(results_import))
