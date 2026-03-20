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
import re
import subprocess
import sys
import time
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

INFRA_REPO = os.environ.get("INFRA_REPO", "dpaia/infrastructure")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

# Stale check threshold: checks in_progress longer than this are considered stuck
STALE_CHECK_HOURS = 2

# Known pipeline check names
PIPELINE_CHECK_NAMES = {"Datapoint Verification", "Datapoint Generation", "Datapoint Validation"}


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


# ---------------------------------------------------------------------------
# Rate-limited API helper
# ---------------------------------------------------------------------------

API_CALL_DELAY = 0.1  # 100ms between calls to avoid secondary rate limits
_last_api_call = 0.0


def gh_rate_limited(*args: str, check: bool = True) -> str:
    """Run gh CLI with rate limit awareness and retry."""
    global _last_api_call
    elapsed = time.time() - _last_api_call
    if elapsed < API_CALL_DELAY:
        time.sleep(API_CALL_DELAY - elapsed)

    for attempt in range(3):
        _last_api_call = time.time()
        result = subprocess.run(
            ["gh", "api", "--include", *args],
            capture_output=True, text=True,
            timeout=60,
        )
        # --include prepends HTTP headers to stdout; split them off
        stdout = result.stdout or ""
        headers_text = ""
        body = stdout
        if "\r\n\r\n" in stdout:
            headers_text, body = stdout.split("\r\n\r\n", 1)
        elif "\n\n" in stdout:
            headers_text, body = stdout.split("\n\n", 1)

        if result.returncode == 0:
            return body.strip()

        stderr_lower = (result.stderr or "").lower()
        if "rate limit" in stderr_lower or "abuse" in stderr_lower or "secondary" in stderr_lower:
            # Try to parse X-RateLimit-Reset or Retry-After from response headers
            wait = _parse_rate_limit_wait(headers_text, default=60 * (attempt + 1))
            print(f"  Rate limited, waiting {wait}s (attempt {attempt + 1}/3)")
            time.sleep(wait)
            continue

        if check:
            print(f"  gh api {' '.join(args[:2])}... failed: {result.stderr.strip()}", file=sys.stderr)
        return ""
    return ""


def _parse_rate_limit_wait(headers_text: str, default: int) -> int:
    """Parse wait time from rate limit response headers."""
    # Try Retry-After header first (used for secondary rate limits)
    retry_match = re.search(r"(?i)retry-after:\s*(\d+)", headers_text)
    if retry_match:
        return int(retry_match.group(1))

    # Try X-RateLimit-Reset (unix timestamp)
    reset_match = re.search(r"(?i)x-ratelimit-reset:\s*(\d+)", headers_text)
    if reset_match:
        reset_time = int(reset_match.group(1))
        wait = max(1, reset_time - int(time.time()))
        return min(wait, 300)  # Cap at 5 minutes

    return default


# ---------------------------------------------------------------------------
# Workflow dispatch
# ---------------------------------------------------------------------------

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

def get_check_runs(owner: str, repo: str, sha: str) -> list[dict]:
    """Get all check runs for a commit SHA with pagination."""
    out = gh_rate_limited(
        "--paginate", "--slurp",
        f"repos/{owner}/{repo}/commits/{sha}/check-runs",
        "--jq", '[.[].check_runs[]] | unique_by(.id)',
        check=False,
    )
    if not out.strip():
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return []


def get_check_count(owner: str, repo: str, sha: str, check_name: str) -> int:
    """Count check runs matching check_name on a commit SHA."""
    checks = get_check_runs(owner, repo, sha)
    return sum(1 for cr in checks if cr.get("name") == check_name)


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


def check_stale_checks(eval_items: list[dict], dataset_items: list[dict], result: SweepResult):
    """Detect and repair check runs stuck in_progress for longer than STALE_CHECK_HOURS."""
    print("\n=== Checking for stale in_progress check runs ===")

    now = datetime.now(timezone.utc)

    # Collect PRs to check — only statuses where workflows are expected
    ACTIVE_STATUSES = {"Review", "Verified", "Validating"}
    prs_to_check: list[tuple[str, str, str, int]] = []  # (owner, repo, sha, number)

    for item in eval_items:
        status = item["fields"].get("Status")
        if status not in ACTIVE_STATUSES:
            continue
        if item.get("content_type") != "PullRequest":
            continue
        head_sha = item.get("head_sha")
        if head_sha:
            prs_to_check.append((item["owner"], item["repo"], head_sha, item["number"]))

    for item in dataset_items:
        if item.get("state") not in ("OPEN", "open"):
            continue
        head_sha = item.get("head_sha")
        if head_sha:
            owner = item.get("owner", "dpaia")
            repo = item.get("repo", "dataset")
            prs_to_check.append((owner, repo, head_sha, item["number"]))

    # Deduplicate by SHA to avoid redundant API calls
    seen_shas: set[str] = set()
    stale_count = 0

    for owner, repo, sha, number in prs_to_check:
        key = f"{owner}/{repo}@{sha}"
        if key in seen_shas:
            continue
        seen_shas.add(key)

        checks = get_check_runs(owner, repo, sha)
        for cr in checks:
            if cr.get("status") != "in_progress":
                continue
            if cr.get("name") not in PIPELINE_CHECK_NAMES:
                continue

            started_at_str = cr.get("started_at")
            if not started_at_str:
                continue

            try:
                started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            age_hours = (now - started_at).total_seconds() / 3600
            if age_hours < STALE_CHECK_HOURS:
                continue

            check_id = cr["id"]
            check_name = cr["name"]
            result.issue(
                f"{owner}/{repo}#{number} check '{check_name}' (ID {check_id}) "
                f"stuck in_progress for {age_hours:.1f}h (started {started_at_str})"
            )

            if DRY_RUN:
                print(f"  [DRY RUN] would PATCH check {check_id} to timed_out")
                result.repaired(f"Would mark check {check_id} as timed_out")
                stale_count += 1
                continue

            # PATCH the check to completed/timed_out
            patch_out = gh_rate_limited(
                "-X", "PATCH",
                f"repos/{owner}/{repo}/check-runs/{check_id}",
                "-f", "status=completed",
                "-f", "conclusion=timed_out",
                "-f", f"completed_at={now.isoformat()}",
                "-f", "output[title]=Timed out",
                "-f", "output[summary]=Check was stuck in_progress and was cleaned up by sweep pipeline.",
                check=False,
            )
            if patch_out or patch_out == "":
                result.repaired(f"Marked check {check_id} ({check_name}) as timed_out")
                stale_count += 1
            else:
                print(f"  Failed to patch check {check_id}", file=sys.stderr)

    print(f"  Scanned {len(seen_shas)} unique SHAs, found {stale_count} stale checks")


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
    check_stale_checks(eval_items, dataset_items, result)

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
