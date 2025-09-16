#!/usr/bin/env python3
import os
import sys
import json
from utils.generate_data import generate_patches

"""
java_verify_ext.py

Reads an instance JSON from a file (the URL from the Project "Data" field should be
downloaded by the workflow beforehand), computes a new patch based on commits
between base_commit and the external repository branch head (commit SHAs are
collected in the workflow), and replaces the "patch" field in the JSON. The
resulting JSON is printed to stdout.

Environment variables used:
- DATA_JSON_PATH: Path to the downloaded JSON file from the Project "Data" field (required)
- EXTERNAL_ORG: External GitHub organization (required)
- EXTERNAL_REPO: External GitHub repository (required)
- EXTERNAL_BRANCH: External branch name (optional, informational)
- COMMITS: Newline-separated list of commit SHAs to generate patches for (required)
- GH_TOKEN: GitHub token (required for GitHub CLI used inside generate_patches)
- EXT_GH_TOKEN: GitHub token for external repository (required for GitHub CLI used inside generate_patches)
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

def all_source_files():
    return False

def main():
    data_json_path = os.environ.get("DATA_JSON_PATH", "").strip()
    external_org = os.environ.get("EXTERNAL_ORG", "").strip()
    external_repo = os.environ.get("EXTERNAL_REPO", "").strip()
    _external_branch = os.environ.get("EXTERNAL_BRANCH", "").strip()

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

    commits = read_commits_env()

    if not external_org or not external_repo:
        eprint("EXTERNAL_ORG or EXTERNAL_REPO is missing; will keep original patch")
        new_patch = original_patch
    else:
        # Compute new patches for the external repo based on collected commits
        try:
            source_patch, test_patch_ext = generate_patches(external_org, external_repo, commits, os.environ.get("EXT_GH_TOKEN", os.environ.get("GH_TOKEN", "")), all_source_files)
            eprint(
                f"Generated source patch for external repo: {source_patch}"
            )
            # Only replace the main patch as per requirements
            new_patch = source_patch
            # We keep the original test_patch from the JSON (do not overwrite)
        except Exception as e:
            eprint(f"Failed to generate patches for external repo: {e}")
            new_patch = original_patch

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
