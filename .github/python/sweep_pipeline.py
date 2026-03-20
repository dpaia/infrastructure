#!/usr/bin/env python3
"""
Pipeline Sweep — detect and repair state inconsistencies.

Reads pre-queried project items (JSON) from eval projects and the dataset metadata
project, identifies inconsistencies across all pipeline stages, and dispatches
repair workflows via `gh workflow run`.

Usage:
    python sweep_pipeline.py --eval-items eval.json --dataset-items dataset.json

Environment:
    GH_TOKEN          — GitHub token for API calls and workflow dispatches
    INFRA_REPO        — Infrastructure repo (default: dpaia/infrastructure)
    DRY_RUN           — If "true", print repairs without dispatching
"""

import argparse
import json
import os
import subprocess
import sys
import time


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

INFRA_REPO = os.environ.get("INFRA_REPO", "dpaia/infrastructure")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"


def gh(*args: str, check: bool = True) -> str:
    """Run a gh CLI command and return stdout."""
    result = subprocess.run(
        ["gh", *args],
        capture_output=True, text=True,
        timeout=30,
    )
    if check and result.returncode != 0:
        print(f"  gh {' '.join(args[:3])}... failed: {result.stderr.strip()}", file=sys.stderr)
        return ""
    return result.stdout.strip()


def dispatch(workflow: str, inputs: dict[str, str]) -> bool:
    """Dispatch a workflow via gh CLI. Returns True on success."""
    args = ["workflow", "run", workflow, "--repo", INFRA_REPO]
    for k, v in inputs.items():
        args += ["-f", f"{k}={v}"]

    if DRY_RUN:
        flat = " ".join(f"{k}={v}" for k, v in inputs.items())
        print(f"  [DRY RUN] gh workflow run {workflow} {flat}")
        return True

    result = subprocess.run(
        ["gh", *args],
        capture_output=True, text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print(f"  dispatch failed: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def run_key() -> str:
    """Generate a sweep-prefixed run key."""
    return f"sweep-{int(time.time())}-{os.getpid()}"


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------

def get_check_count(owner: str, repo: str, sha: str, check_name: str) -> int:
    """Count check runs matching check_name on a commit SHA."""
    out = gh(
        "api", f"repos/{owner}/{repo}/commits/{sha}/check-runs",
        "--jq", f'[.check_runs[] | select(.name == "{check_name}")] | length',
        check=False,
    )
    try:
        return int(out)
    except (ValueError, TypeError):
        return 0


def build_source_url(owner: str, repo: str, number: int) -> str:
    return f"https://github.com/{owner}/{repo}/pull/{number}"


# ---------------------------------------------------------------------------
# Individual sweep checks
# ---------------------------------------------------------------------------

class SweepResult:
    def __init__(self):
        self.issues: list[str] = []
        self.repairs: int = 0

    def issue(self, msg: str):
        self.issues.append(msg)
        print(f"INCONSISTENCY: {msg}")

    def repaired(self, msg: str):
        self.repairs += 1
        print(f"  -> {msg}")


def check_review_without_verification(eval_items: list[dict], result: SweepResult):
    """PRs in Review without a Datapoint Verification check on current HEAD."""
    print("=== Checking source PRs in Review without verification ===")
    for item in eval_items:
        if item["fields"].get("Status") != "Review":
            continue
        if item.get("content_type") != "PullRequest":
            continue

        verification = item["fields"].get("Verification")
        if verification and verification not in ("Pending", None):
            continue  # has a non-pending verification — likely ok

        owner = item["owner"]
        repo = item["repo"]
        number = item["number"]
        head_sha = item.get("head_sha")
        eval_type = item["eval_type"]

        if not head_sha:
            result.issue(f"{owner}/{repo}#{number} in Review but no head SHA available")
            continue

        checks = get_check_count(owner, repo, head_sha, "Datapoint Verification")
        if checks == 0:
            result.issue(f"{owner}/{repo}#{number} in Review but no verification check for SHA {head_sha[:7]}")
            ok = dispatch("verify-source_v2.yml", {
                "organization": owner,
                "repository": repo,
                "pr_number": str(number),
                "eval_type": eval_type,
                "run_key": run_key(),
            })
            if ok:
                result.repaired(f"Dispatched verification (eval_type={eval_type})")


def check_stale_verification(eval_items: list[dict], result: SweepResult):
    """Items with Verification=Passed but Status not in Verified/Done."""
    print("\n=== Checking stale Verification on items outside Verified/Done ===")
    for item in eval_items:
        if item["fields"].get("Verification") != "Passed":
            continue
        status = item["fields"].get("Status")
        if status in ("Verified", "Done"):
            continue

        owner = item["owner"]
        repo = item["repo"]
        number = item["number"]
        eval_type = item["eval_type"]
        project_number = item["project_number"]

        result.issue(f"{owner}/{repo}#{number} has Status='{status}' but Verification='Passed' (stale)")
        ok = dispatch("sync-project-fields_v2.yml", {
            "organization": owner,
            "repository": repo,
            "pr_number": str(number),
            "operation": "clear-verification",
            "eval_project_number": str(project_number),
            "run_key": run_key(),
        })
        if ok:
            result.repaired(f"Dispatched clear-verification (eval_type={eval_type})")


def check_verified_inconsistencies(eval_items: list[dict], dataset_items: list[dict], result: SweepResult):
    """
    Comprehensive check for PRs in Verified status.
    Detects:
    - Verified with Verification != Passed (guard bypass)
    - Verified with closed/merged source PR (stale board state)
    - Verified without a dataset PR (generation not triggered)
    - Verified with a failed dataset PR (needs re-generation)
    """
    print("\n=== Checking source PRs in Verified for inconsistencies ===")

    # Build a lookup: source PR URL -> dataset items
    dataset_by_source: dict[str, list[dict]] = {}
    for di in dataset_items:
        source_url = di["fields"].get("Source PR")
        if source_url:
            dataset_by_source.setdefault(source_url, []).append(di)

    verified_items = [
        item for item in eval_items
        if item["fields"].get("Status") == "Verified"
        and item.get("content_type") == "PullRequest"
    ]

    for item in verified_items:
        owner = item["owner"]
        repo = item["repo"]
        number = item["number"]
        eval_type = item["eval_type"]
        verification = item["fields"].get("Verification")
        pr_state = item.get("state")
        source_url = build_source_url(owner, repo, number)

        # 1. Verification must be Passed to be in Verified
        if verification != "Passed":
            result.issue(
                f"{owner}/{repo}#{number} in Verified but Verification='{verification or 'not set'}' (expected Passed)"
            )
            # Don't auto-repair — this needs manual investigation
            continue

        # 2. Source PR should be open
        if pr_state and pr_state not in ("OPEN", "open"):
            result.issue(f"{owner}/{repo}#{number} in Verified but PR state is '{pr_state}'")
            # Don't auto-repair — closed PRs in Verified need manual review
            continue

        # 3. Check for dataset PR existence
        dataset_prs = dataset_by_source.get(source_url, [])
        if not dataset_prs:
            result.issue(f"{owner}/{repo}#{number} in Verified but no dataset PR found")
            ok = dispatch("generate-datapoint_v2.yml", {
                "organization": owner,
                "repository": repo,
                "pr_number": str(number),
                "eval_type": eval_type,
                "run_key": run_key(),
            })
            if ok:
                result.repaired(f"Dispatched generation (eval_type={eval_type})")
            continue

        # 4. Check dataset PR state — if all are closed (not merged), generation may have failed
        open_or_merged = [
            dp for dp in dataset_prs
            if dp.get("state") in ("OPEN", "open", "MERGED", "merged")
        ]
        if not open_or_merged:
            all_statuses = [dp["fields"].get("Status", "?") for dp in dataset_prs]
            result.issue(
                f"{owner}/{repo}#{number} in Verified but all dataset PRs are closed "
                f"(statuses: {', '.join(all_statuses)}) — may need re-generation"
            )
            ok = dispatch("generate-datapoint_v2.yml", {
                "organization": owner,
                "repository": repo,
                "pr_number": str(number),
                "eval_type": eval_type,
                "run_key": run_key(),
            })
            if ok:
                result.repaired(f"Dispatched re-generation (eval_type={eval_type})")


def check_merged_not_done(dataset_items: list[dict], result: SweepResult):
    """Merged dataset PRs not marked Done."""
    print("\n=== Checking merged dataset PRs not marked Done ===")
    for item in dataset_items:
        if item.get("state") not in ("MERGED", "merged"):
            continue
        if item["fields"].get("Status") == "Done":
            continue

        number = item["number"]
        title = item.get("title", "")
        current_status = item["fields"].get("Status", "?")
        owner = item.get("owner", "dpaia")
        repo = item.get("repo", "dataset")

        result.issue(f"Dataset PR #{number} ('{title}') is merged but status is '{current_status}'")
        ok = dispatch("on-datapoint-merged_v2.yml", {
            "organization": owner,
            "repository": repo,
            "pr_number": str(number),
            "run_key": run_key(),
        })
        if ok:
            result.repaired("Dispatched post-merge repair")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Pipeline sweep — detect and repair inconsistencies")
    parser.add_argument("--eval-items", required=True, help="Path to merged eval items JSON file")
    parser.add_argument("--dataset-items", required=True, help="Path to dataset items JSON file")
    parser.add_argument("--output", help="Path to write summary JSON (optional)")
    args = parser.parse_args()

    with open(args.eval_items) as f:
        eval_items = json.load(f)
    with open(args.dataset_items) as f:
        dataset_items = json.load(f)

    print(f"Loaded {len(eval_items)} eval items, {len(dataset_items)} dataset items")
    if DRY_RUN:
        print("DRY RUN mode — no workflows will be dispatched\n")

    result = SweepResult()

    check_review_without_verification(eval_items, result)
    check_stale_verification(eval_items, result)
    check_verified_inconsistencies(eval_items, dataset_items, result)
    check_merged_not_done(dataset_items, result)

    print(f"\n=== Sweep complete ===")
    print(f"Issues found: {len(result.issues)}")
    print(f"Repairs dispatched: {result.repairs}")
    if not result.issues:
        print("All states consistent")

    # Write summary for GITHUB_OUTPUT
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"issues_found={len(result.issues)}\n")
            f.write(f"repairs={result.repairs}\n")

    # Write detailed output if requested
    if args.output:
        with open(args.output, "w") as f:
            json.dump({
                "issues_found": len(result.issues),
                "repairs": result.repairs,
                "issues": result.issues,
            }, f, indent=2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
