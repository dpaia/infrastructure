"""Parse unified diffs and apply them remotely via PyGithub Git Data API.

No local cloning required — all operations use the GitHub API to read blobs,
apply patches in-memory, create new blobs/trees/commits, and create branch refs.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any

import unidiff
import whatthepatch

logger = logging.getLogger(__name__)


@dataclass
class PatchResult:
    """Result of applying patches to a repository."""

    commit_sha: str
    branch_ref: str
    base_branch_ref: str
    files_modified: list[str]
    files_added: list[str]
    files_deleted: list[str]


def parse_patch(patch_text: str) -> unidiff.PatchSet:
    """Parse a unified diff into a PatchSet.

    Args:
        patch_text: Unified diff text.

    Returns:
        Parsed PatchSet object.

    Raises:
        ValueError: If the patch cannot be parsed.
    """
    if not patch_text or not patch_text.strip():
        raise ValueError("Empty patch text")
    try:
        return unidiff.PatchSet(patch_text)
    except Exception as e:
        raise ValueError(f"Failed to parse patch: {e}")


def apply_patch_to_content(original_content: str, diff_text: str) -> str:
    """Apply a diff to file content in-memory using whatthepatch.

    Args:
        original_content: Original file content.
        diff_text: Unified diff text for a single file.

    Returns:
        Patched file content.

    Raises:
        ValueError: If the patch cannot be applied.
    """
    diffs = list(whatthepatch.parse_patch(diff_text))
    if not diffs:
        raise ValueError("No diffs found in patch text")

    original_lines = original_content.split("\n")
    # Remove trailing empty line that split() adds for content ending with newline
    if original_lines and original_lines[-1] == "":
        original_lines = original_lines[:-1]

    for diff in diffs:
        if diff.changes is None:
            continue
        result = whatthepatch.apply_diff(diff, original_lines)
        if result is None:
            raise ValueError("Failed to apply diff — patch does not match content")
        original_lines = result

    return "\n".join(original_lines) + "\n"


def apply_patches_via_api(
    repo,  # github.Repository.Repository
    base_commit_sha: str,
    patch_text: str,
    test_patch_text: str | None = None,
    commit_message: str = "Import SWE-bench task",
    branch_name: str | None = None,
) -> PatchResult:
    """Apply patches to a GitHub repository via the Git Data API.

    1. Parse the unified diff into per-file patches
    2. For each modified file: fetch blob, apply patch in-memory, create new blob
    3. Build a new tree with all changes
    4. Create a commit pointing to the new tree
    5. Create a branch ref pointing to the commit

    Args:
        repo: PyGithub Repository object (the fork).
        base_commit_sha: SHA of the base commit to apply patches on top of.
        patch_text: Unified diff for the golden patch.
        test_patch_text: Optional unified diff for the test patch.
        commit_message: Commit message for the new commit.
        branch_name: Branch name (without refs/heads/ prefix). If None, no branch created.

    Returns:
        PatchResult with commit SHA and file lists.

    Raises:
        ValueError: If patches cannot be parsed or applied.
        Exception: If GitHub API calls fail.
    """
    from github import InputGitTreeElement

    # Combine patches
    combined_patch = patch_text
    if test_patch_text:
        combined_patch = patch_text.rstrip("\n") + "\n" + test_patch_text

    patchset = parse_patch(combined_patch)

    files_modified = []
    files_added = []
    files_deleted = []
    tree_elements = []

    base_commit = repo.get_git_commit(base_commit_sha)
    base_tree = base_commit.tree

    for patched_file in patchset:
        # Determine file paths
        source_path = patched_file.source_file
        target_path = patched_file.target_file

        # Strip a/ and b/ prefixes from git diff paths
        if source_path and source_path.startswith("a/"):
            source_path = source_path[2:]
        if target_path and target_path.startswith("b/"):
            target_path = target_path[2:]

        # Handle file operations
        if patched_file.is_added_file:
            # New file — reconstruct content from the patch hunks
            new_content = _reconstruct_added_file(patched_file)
            blob = repo.create_git_blob(new_content, "utf-8")
            tree_elements.append(
                InputGitTreeElement(
                    path=target_path,
                    mode="100644",
                    type="blob",
                    sha=blob.sha,
                )
            )
            files_added.append(target_path)

        elif patched_file.is_removed_file:
            # Deleted file
            tree_elements.append(
                InputGitTreeElement(
                    path=source_path,
                    mode="100644",
                    type="blob",
                    sha=None,
                )
            )
            files_deleted.append(source_path)

        else:
            # Modified file — fetch current content, apply patch
            try:
                file_content = repo.get_contents(source_path, ref=base_commit_sha)
            except Exception as e:
                raise ValueError(
                    f"Failed to fetch file '{source_path}' at {base_commit_sha}: {e}"
                )

            # Decode content
            if file_content.encoding == "base64":
                original = base64.b64decode(file_content.content).decode("utf-8")
            else:
                original = file_content.decoded_content.decode("utf-8")

            # Build per-file diff text for whatthepatch
            file_diff = str(patched_file)
            new_content = apply_patch_to_content(original, file_diff)

            blob = repo.create_git_blob(new_content, "utf-8")
            tree_elements.append(
                InputGitTreeElement(
                    path=target_path,
                    mode="100644",
                    type="blob",
                    sha=blob.sha,
                )
            )
            files_modified.append(target_path)

    if not tree_elements:
        raise ValueError("Patch produced no file changes")

    # Create new tree
    new_tree = repo.create_git_tree(tree_elements, base_tree)

    # Create commit
    new_commit = repo.create_git_commit(
        message=commit_message,
        tree=new_tree,
        parents=[base_commit],
    )

    # Create branch refs if requested
    branch_ref = ""
    base_branch_ref = ""
    if branch_name:
        # "before" branch: points at the unmodified base_commit
        base_branch_name = f"{branch_name}/before"
        base_ref_name = f"refs/heads/{base_branch_name}"
        _create_or_update_ref(repo, base_branch_name, base_commit_sha)
        base_branch_ref = base_ref_name

        # "after" branch: points at the new commit with patches applied
        after_branch_name = f"{branch_name}/after"
        after_ref_name = f"refs/heads/{after_branch_name}"
        _create_or_update_ref(repo, after_branch_name, new_commit.sha)
        branch_ref = after_ref_name

    return PatchResult(
        commit_sha=new_commit.sha,
        branch_ref=branch_ref,
        base_branch_ref=base_branch_ref,
        files_modified=files_modified,
        files_added=files_added,
        files_deleted=files_deleted,
    )


def _create_or_update_ref(repo, branch_name: str, sha: str) -> None:
    """Create a branch ref or update it if it already exists."""
    ref_name = f"refs/heads/{branch_name}"
    try:
        repo.create_git_ref(ref=ref_name, sha=sha)
    except Exception:
        try:
            ref = repo.get_git_ref(f"heads/{branch_name}")
            ref.edit(sha=sha, force=True)
        except Exception as e:
            raise ValueError(
                f"Failed to create or update branch '{branch_name}': {e}"
            )


def _reconstruct_added_file(patched_file) -> str:
    """Reconstruct file content from an added file's patch hunks."""
    lines = []
    for hunk in patched_file:
        for line in hunk:
            if line.is_added:
                lines.append(line.value)
    content = "\n".join(lines)
    if not content.endswith("\n"):
        content += "\n"
    return content
