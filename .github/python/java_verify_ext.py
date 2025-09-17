#!/usr/bin/env python3
import os
import sys
import json
import tempfile
import shutil
import zipfile
from utils.generate_data import generate_patches, run_subprocess

"""
java_verify_ext.py

Reads an instance JSON from a file (the URL from the Project "Data" field should be
downloaded by the workflow beforehand), computes a new patch based on either:
- Fork mode (IS_FORK=true): commits collected by the workflow for the external repo
- Non-fork mode (IS_FORK not set or false): diff between original repo base_commit and the head of EXTERNAL_ORG/EXTERNAL_REPO EXTERNAL_BRANCH
and replaces the "patch" field in the JSON. The resulting JSON is printed to stdout.

Environment variables used:
- DATA_JSON_PATH: Path to the downloaded JSON file from the Project "Data" field (required)
- EXTERNAL_ORG: External GitHub organization (required)
- EXTERNAL_REPO: External GitHub repository (required)
- EXTERNAL_BRANCH: External branch name (optional; if missing, default branch is used in non-fork mode)
- COMMITS: Newline-separated list of commit SHAs to generate patches for (used in fork mode)
- GH_TOKEN: GitHub token (used by GitHub CLI)
- EXT_GH_TOKEN: GitHub token for external repository (if provided, preferred over GH_TOKEN)
- IS_FORK: If set to true, use the existing behaviour based on commits
"""


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def read_commits_env() -> list:
    commits_raw = os.environ.get("COMMITS", "").strip()
    if not commits_raw:
        return []
    # Allow either JSON array or newline-separated list
    try:
        parsed = json.loads(commits_raw)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except Exception:
        pass
    return [line.strip() for line in commits_raw.splitlines() if line.strip()]


def all_source_files(file_path):
    return False


def parse_repo_owner_and_name(repo_value: str):
    # Accept formats like "org/repo" or "https://github.com/org/repo(.git)" or with trailing .git
    val = (repo_value or "").strip()
    if val.endswith(".git"):
        val = val[:-4]
    prefixes = ["https://github.com/", "http://github.com/", "git@github.com:"]
    for p in prefixes:
        if val.startswith(p):
            val = val[len(p):]
            break
    # Now expect org/repo
    if "/" in val:
        parts = val.split("/", 1)
        return parts[0], parts[1]
    return "", ""


def get_token():
    return os.environ.get("EXT_GH_TOKEN", os.environ.get("GH_TOKEN", ""))


def get_external_branch_or_default(external_org: str, external_repo: str, requested_branch: str) -> str:
    branch = (requested_branch or "").strip()
    if branch:
        return branch
    token = get_token()
    try:
        cmd = [
            "gh", "api",
            f"repos/{external_org}/{external_repo}",
            "--jq", ".default_branch",
        ]
        # gh picks up GH_TOKEN from env; header is optional but we keep parity with other calls
        if token:
            cmd.extend(["-H", f"Authorization: Bearer {token}"])
        res = run_subprocess(cmd, capture_output=True, text=True, check=True)
        branch = (res.stdout or "").strip()
        return branch
    except Exception as e:
        eprint(f"Failed to fetch default branch for {external_org}/{external_repo}: {e}")
        return ""


def compare_patch_between_base_and_external(base_org: str, base_repo: str, base_commit: str, external_org: str, external_repo: str, external_branch: str) -> str:
    if not base_org or not base_repo or not base_commit:
        return ""
    if not external_org or not external_repo or not external_branch:
        return ""

    ws_dir = tempfile.mkdtemp(prefix="compare_ws_")
    base_dir = os.path.join(ws_dir, "a")
    ext_dir = os.path.join(ws_dir, "b")
    try:
        os.makedirs(base_dir, exist_ok=True)
        os.makedirs(ext_dir, exist_ok=True)

        # Resolve external branch head SHA (works if 'external_branch' is already a SHA too)
        head_sha = resolve_branch_head_sha(external_org, external_repo, external_branch)
        ext_ref = head_sha or external_branch
        if not ext_ref:
            eprint(f"Failed to resolve external head for {external_org}/{external_repo}:{external_branch}")
            return ""

        # Download and extract both repos at desired refs
        if not download_and_extract_zipball(base_org, base_repo, base_commit, base_dir):
            eprint(f"Failed to download/extract base repo {base_org}/{base_repo}@{base_commit}")
            return ""
        if not download_and_extract_zipball(external_org, external_repo, ext_ref, ext_dir):
            eprint(f"Failed to download/extract external repo {external_org}/{external_repo}@{ext_ref}")
            return ""

        # Compute diff locally between the two directories
        cmd = [
            "git", "-C", ws_dir, "diff", "--no-index", "--binary", "--", "a", "b"
        ]
        res = run_subprocess(cmd, capture_output=True, text=True, check=False)

        # git diff returns code 1 when differences are found
        if res.returncode not in (0, 1):
            if getattr(res, "stderr", ""):
                eprint(f"git diff failed: {res.stderr}")
            return ""

        patch = (res.stdout or "").strip()
        if res.returncode == 0 or not patch:
            # No differences
            return ""

        # Normalize path prefixes to match conventional a/ and b/
        # This avoids paths like a/a/ and b/b/ in headers when diffing dirs named 'a' and 'b'
        patch = patch.replace("\ndiff --git a/a/", "\ndiff --git a/")
        patch = patch.replace("\n--- a/a/", "\n--- a/")
        patch = patch.replace("\n+++ b/b/", "\n+++ b/")
        patch = patch.replace(" a/a/", " a/")
        patch = patch.replace(" b/b/", " b/")
        patch = patch.replace("\nrename from a/a/", "\nrename from a/")
        patch = patch.replace("\nrename to b/b/", "\nrename to b/")

        return patch
    except Exception as e:
        eprint(f"Failed to generate local compare patch: {e}")
        return ""
    finally:
        try:
            shutil.rmtree(ws_dir, ignore_errors=True)
        except Exception:
            pass


def resolve_branch_head_sha(org: str, repo: str, branch: str) -> str:
    branch = (branch or "").strip()
    if not branch:
        return ""
    token = get_token()
    try:
        cmd = [
            "gh", "api",
            f"repos/{org}/{repo}/commits/{branch}",
            "--jq", ".sha",
        ]
        if token:
            cmd.extend(["-H", f"Authorization: Bearer {token}"])
        res = run_subprocess(cmd, capture_output=True, text=True, check=True)
        return (res.stdout or "").strip()
    except Exception as e:
        eprint(f"Failed to resolve head sha via GitHub API for {org}/{repo}@{branch}: {e}")
        return ""


def download_and_extract_zipball(org: str, repo: str, ref: str, target_dir: str) -> bool:
    if not org or not repo or not ref or not target_dir:
        return False
    token = get_token()
    try:
        os.makedirs(target_dir, exist_ok=True)
        parent = os.path.dirname(target_dir)
        # Save as a.zip or b.zip next to target dir
        zip_path = os.path.join(parent, f"{os.path.basename(target_dir)}.zip")

        # Download the zipball of the repository at the given ref
        cmd = [
            "gh", "api",
            f"repos/{org}/{repo}/zipball/{ref}",
            "--output", zip_path,
        ]
        if token:
            cmd.extend(["-H", f"Authorization: Bearer {token}"])
        # gh writes directly to file; no need to capture stdout
        run_subprocess(cmd, capture_output=False, check=True)

        # Extract to a temporary directory
        extract_tmp = os.path.join(parent, f".extract_{os.path.basename(target_dir)}")
        if os.path.isdir(extract_tmp):
            shutil.rmtree(extract_tmp, ignore_errors=True)
        os.makedirs(extract_tmp, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_tmp)

        # GitHub zipball has a single top-level directory; move its contents into target_dir
        entries = [os.path.join(extract_tmp, name) for name in os.listdir(extract_tmp)]
        root_dirs = [p for p in entries if os.path.isdir(p)]
        root = root_dirs[0] if root_dirs else extract_tmp

        for name in os.listdir(root):
            src = os.path.join(root, name)
            dst = os.path.join(target_dir, name)
            if os.path.exists(dst):
                if os.path.isdir(dst):
                    shutil.rmtree(dst, ignore_errors=True)
                else:
                    try:
                        os.remove(dst)
                    except Exception:
                        pass
            shutil.move(src, dst)

        # Cleanup temp artifacts
        try:
            os.remove(zip_path)
        except Exception:
            pass
        shutil.rmtree(extract_tmp, ignore_errors=True)
        return True
    except Exception as e:
        eprint(f"Failed to download/extract zipball for {org}/{repo}@{ref}: {e}")
        return False


def main():
    data_json_path = os.environ.get("DATA_JSON_PATH", "").strip()
    external_org = os.environ.get("EXTERNAL_ORG", "").strip()
    external_repo = os.environ.get("EXTERNAL_REPO", "").strip()
    external_branch_env = os.environ.get("EXTERNAL_BRANCH", "").strip()
    is_fork = os.environ.get("IS_FORK", "false")

    if not data_json_path:
        eprint("DATA_JSON_PATH is not provided")
        sys.exit(1)

    if not os.path.isfile(data_json_path):
        eprint(f"DATA_JSON_PATH file not found: {data_json_path}")
        sys.exit(1)

    # Load original JSON
    with open(data_json_path, "r", encoding="utf-8") as f:
        try:
            original = json.load(f)
        except Exception as e:
            eprint(f"Failed to parse JSON from {data_json_path}: {e}")
            sys.exit(1)

    # Extract base fields
    base_commit = str(original.get("base_commit", ""))
    original_patch = original.get("patch", "")
    original_test_patch = original.get("test_patch", "")

    # Default to original patch
    new_patch = original_patch

    if not external_org or not external_repo:
        eprint("EXTERNAL_ORG or EXTERNAL_REPO is missing; will keep original patch")
    else:
        if is_fork:
            # Existing behaviour based on commit list
            commits = read_commits_env()
            try:
                source_patch, _test_patch_ext = generate_patches(
                    external_org,
                    external_repo,
                    commits,
                    os.environ.get("EXT_GH_TOKEN", os.environ.get("GH_TOKEN", "")),
                    all_source_files,
                )
                eprint("Generated source patch for external repo (fork mode)")
                new_patch = source_patch
            except Exception as e:
                eprint(f"Failed to generate patches for external repo (fork mode): {e}")
        else:
            # Non-fork mode: compare base_commit of original repo vs external repo branch head
            repo_value = str(original.get("repo", ""))
            base_org, base_repo = parse_repo_owner_and_name(repo_value)
            if not base_org or not base_repo or not base_commit:
                eprint("Missing repo/base_commit in JSON; cannot compute compare patch. Keeping original patch.")
            else:
                # Resolve external branch (from env or default)
                branch = get_external_branch_or_default(external_org, external_repo, external_branch_env)
                if not branch:
                    eprint("Failed to resolve external branch; keeping original patch")
                else:
                    patch = compare_patch_between_base_and_external(base_org, base_repo, base_commit, external_org, external_repo, branch)
                    if patch:
                        new_patch = patch
                        eprint(f"Generated compare patch between {base_org}/{base_repo}@{base_commit} and {external_org}/{external_repo} {branch}")
                    else:
                        eprint("Compare patch is empty or failed; keeping original patch")

    # Build modified JSON
    modified = dict(original)
    modified["patch"] = new_patch if new_patch is not None else ""
    # Preserve test_patch from the original JSON
    modified["test_patch"] = original_test_patch if original_test_patch is not None else ""
    # Ensure base_commit remains as in the original JSON
    if base_commit:
        modified["base_commit"] = base_commit

    # Output resulting JSON
    print(json.dumps(modified))


if __name__ == "__main__":
    main()
