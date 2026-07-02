#!/usr/bin/env python3
"""Render a Harbor task for a source PR from a central template + PR overrides.

Harbor is a second output format, orthogonal to eval_type. This script:

  1. Fetches PR data (diff, commits, description sections).
  2. Resolves metadata: .harbor/metadata.json (PR head) falls back to the
     existing .ee-bench/codegen/metadata.json chain (default branch base,
     PR branch deep-merged on top).
  3. Checks harbor capability (explicit templates.harbor ref, central default
     template, or .harbor/ in the PR head tree; templates.harbor=false opts
     out). Not capable -> prints harbor_status=skipped and exits 0.
  4. Merges the template dir with PR .harbor/ file overrides and validates
     required files (task.toml, environment/Dockerfile, tests/test.sh).
  5. Splits the PR patch into gold + test patches.
  6. Renders every merged file with the same Jinja context as .ee-bench
     rendering (instance.* built-ins + top-level metadata fields).
  7. Injects instruction.md, solution/patch.diff, solution/solve.sh and
     tests/test_patch.diff.
  8. Post-render checks: task.toml parses as TOML, no unrendered
     {{ instance.* }} markers remain.
  9. Writes the task to <output_dir>/<language>/<repo_name>/<instance_id>/
     (mirrors _harbor_converted/ in the dataset repo).

Interface (same --set convention as export_unified.py):

  python export_harbor_template.py \
    --set REPO=dpaia/feature-service --set PR_NUMBER=42 \
    --set TEMPLATES_REPO=dpaia/.dpaia_templates \
    --set TEMPLATES_PATH=harbor \
    --output-dir out/harbor

Machine-readable outputs (stdout + $GITHUB_OUTPUT when set):
  harbor_status=generated|skipped
  harbor_task_dir=<absolute-ish path>
  harbor_task_rel=<language>/<repo_name>/<instance_id>
  instance_id=<id>
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import stat
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_TEMPLATES_REPO = "dpaia/.dpaia_templates"
DEFAULT_TEMPLATES_PATH = "harbor"
DEFAULT_OUTPUT_DIR = "datasets/harbor_template"

HARBOR_DIR = ".harbor"
HARBOR_METADATA_PATH = f"{HARBOR_DIR}/metadata.json"
EE_BENCH_METADATA_PATH = ".ee-bench/codegen/metadata.json"

REQUIRED_TEMPLATE_FILES = ("task.toml", "environment/Dockerfile", "tests/test.sh")

# Files always executable in the rendered task, regardless of source tree mode.
ALWAYS_EXECUTABLE = ("tests/test.sh", "solution/solve.sh")

UNRENDERED_MARKER_RE = re.compile(r"\{\{\s*instance\.")

_TEST_FIELD_LINE_RE = re.compile(
    r"^\s*(FAIL_TO_PASS|PASS_TO_PASS)\s*:.*$", re.IGNORECASE | re.MULTILINE
)

SOLVE_SH = """#!/usr/bin/env bash
set -euo pipefail

cd "${EE_BENCH_PROJECT_ROOT:-/repo}"
git apply /solution/patch.diff
"""


class HarborExportError(RuntimeError):
    """Hard error: harbor generation was triggered but cannot complete."""


@dataclass
class TaskFile:
    """One file of the merged (template + overlay + injected) Harbor task."""

    content: bytes
    executable: bool = False
    origin: str = ""

    def text(self) -> str | None:
        """Decoded text content, or None when the file is binary."""
        try:
            return self.content.decode("utf-8")
        except UnicodeDecodeError:
            return None


class RepoFiles:
    """Read-only file access to a GitHub repository at a fixed ref."""

    def __init__(self, client, owner: str, repo: str, ref: str):
        self._client = client
        self.owner = owner
        self.repo = repo
        self.ref = ref
        self._tree: dict[str, dict] | None = None

    def tree(self) -> dict[str, dict]:
        """Map of blob path -> {sha, mode} for the whole tree at ref."""
        if self._tree is None:
            try:
                data = self._client.get(
                    f"/repos/{self.owner}/{self.repo}/git/trees/{self.ref}",
                    recursive="true",
                )
            except Exception as exc:
                logger.debug(
                    "Could not list tree for %s/%s@%s: %s",
                    self.owner, self.repo, self.ref, exc,
                )
                data = {}
            self._tree = {
                entry["path"]: {"sha": entry["sha"], "mode": entry.get("mode", "100644")}
                for entry in data.get("tree", [])
                if entry.get("type") == "blob"
            }
        return self._tree

    def subtree(self, prefix: str) -> dict[str, dict]:
        """Blobs under prefix/, keyed by path relative to the prefix."""
        prefix = prefix.rstrip("/") + "/"
        return {
            path[len(prefix):]: entry
            for path, entry in self.tree().items()
            if path.startswith(prefix)
        }

    def read_bytes(self, path: str) -> bytes | None:
        entry = self.tree().get(path)
        if entry is None:
            return None
        blob = self._client.get(
            f"/repos/{self.owner}/{self.repo}/git/blobs/{entry['sha']}"
        )
        if isinstance(blob, dict) and blob.get("encoding") == "base64":
            return base64.b64decode(blob["content"].replace("\n", ""))
        return None

    def read_text(self, path: str) -> str | None:
        data = self.read_bytes(path)
        if data is None:
            return None
        return data.decode("utf-8", errors="replace")


def emit_output(key: str, value: str) -> None:
    """Print a machine-readable output; mirror to $GITHUB_OUTPUT when set."""
    print(f"{key}={value}")
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def render_template(template_str: str, ctx: dict) -> str:
    """Render a Jinja2 template with instance=ctx. Pass-through if no {{ }}.

    Identical rules to EEBenchEnvironmentProvider._render_template.
    """
    if "{{" not in template_str:
        return template_str
    from jinja2 import ChainableUndefined, Environment

    env = Environment(keep_trailing_newline=True, undefined=ChainableUndefined)
    env.filters["tojson"] = json.dumps
    tmpl = env.from_string(template_str)
    return tmpl.render(instance=ctx)


def parse_template_ref(ref: str) -> tuple[str | None, str]:
    """Parse a templates.harbor reference: ``[<owner>/<repo>:]<path>``.

    Returns (repo or None, path). None repo means the default templates repo.
    """
    repo: str | None = None
    path = ref
    if ":" in ref:
        repo, _, path = ref.partition(":")
        if "/" not in repo:
            raise HarborExportError(
                f"Invalid templates.harbor reference {ref!r}: "
                "repo part must be <owner>/<repo>"
            )
    path = path.strip("/")
    if not path or ".." in Path(path).parts:
        raise HarborExportError(f"Invalid templates.harbor path in reference {ref!r}")
    return repo, path


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
    """Ensure legacy test-list fields are also available as expected.*."""
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
        candidates.extend(
            data[source_key] for source_key in source_keys if source_key in data
        )

        normalized = []
        for candidate in candidates:
            normalized = _parse_test_list(candidate)
            if normalized:
                break

        expected[expected_key] = normalized


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base; override wins for non-dict leaves."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _test_list_has_values(value) -> bool:
    if value in (None, ""):
        return False
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return bool(value.strip())
        return bool(parsed)
    return bool(value)


def _expected_has_tests(value) -> bool:
    if not isinstance(value, dict):
        return False
    for key in (
        "fail_to_pass",
        "FAIL_TO_PASS",
        "pass_to_pass",
        "PASS_TO_PASS",
        "fail_to_fail",
        "FAIL_TO_FAIL",
    ):
        if _test_list_has_values(value.get(key)):
            return True
    return False


def resolve_metadata(
    source_repo: RepoFiles,
    source_repo_default: RepoFiles,
    render_ctx: dict,
) -> tuple[dict, str]:
    """Resolve datapoint metadata via the fallback chain.

    1. .harbor/metadata.json from the PR head tree (whole file wins).
    2. .ee-bench/codegen/metadata.json — existing semantics: default-branch
       base with the PR-branch file deep-merged on top.

    Returns (metadata, source_label).
    """
    harbor_raw = source_repo.read_text(HARBOR_METADATA_PATH)
    if harbor_raw is not None:
        try:
            metadata = json.loads(render_template(harbor_raw, render_ctx))
        except Exception as exc:
            raise HarborExportError(f"Failed to parse {HARBOR_METADATA_PATH}: {exc}")
        if not isinstance(metadata, dict):
            raise HarborExportError(f"{HARBOR_METADATA_PATH} must contain a JSON object")
        return metadata, HARBOR_METADATA_PATH

    metadata: dict = {}
    base_raw = source_repo_default.read_text(EE_BENCH_METADATA_PATH)
    if base_raw is not None:
        try:
            metadata = json.loads(render_template(base_raw, render_ctx))
        except Exception as exc:
            logger.warning(
                "Failed to parse %s from default branch: %s", EE_BENCH_METADATA_PATH, exc
            )
            metadata = {}
    pr_raw = source_repo.read_text(EE_BENCH_METADATA_PATH)
    if pr_raw is not None:
        try:
            pr_metadata = json.loads(render_template(pr_raw, render_ctx))
            metadata = _deep_merge(metadata, pr_metadata)
        except Exception as exc:
            logger.warning(
                "Failed to parse %s from PR branch: %s", EE_BENCH_METADATA_PATH, exc
            )
    return metadata, EE_BENCH_METADATA_PATH


def load_repo_files(repo_files: RepoFiles, prefix: str, origin: str) -> dict[str, TaskFile]:
    """Fetch all blobs under prefix/ as TaskFiles keyed by relative path."""
    files: dict[str, TaskFile] = {}
    for rel_path, entry in repo_files.subtree(prefix).items():
        data = repo_files.read_bytes(f"{prefix.rstrip('/')}/{rel_path}")
        if data is None:
            raise HarborExportError(f"Could not fetch {origin}:{prefix}/{rel_path}")
        files[rel_path] = TaskFile(
            content=data,
            executable=entry.get("mode") == "100755",
            origin=origin,
        )
    return files


def resolve_template_files(
    client,
    harbor_ref,
    templates_repo: str,
    templates_path: str,
    source_org: str,
    source_repo_name: str,
    default_branch_of,
) -> tuple[dict[str, TaskFile], str]:
    """Resolve the central template directory per the spec's resolution levels.

    Returns (files, template_label). Empty files dict when no central template
    applies (PR .harbor/ only).
    """
    if isinstance(harbor_ref, str):
        ref_repo, ref_path = parse_template_ref(harbor_ref)
        repo_full = ref_repo or templates_repo
        owner, _, name = repo_full.partition("/")
        repo_files = RepoFiles(client, owner, name, default_branch_of(repo_full))
        files = load_repo_files(repo_files, ref_path, repo_full)
        if not files:
            raise HarborExportError(
                f"templates.harbor reference {harbor_ref!r} does not resolve to any "
                f"files in {repo_full} (explicit references must resolve)"
            )
        return files, f"{repo_full}:{ref_path}"

    default_path = f"{templates_path.rstrip('/')}/{source_org}/{source_repo_name}"
    owner, _, name = templates_repo.partition("/")
    repo_files = RepoFiles(client, owner, name, default_branch_of(templates_repo))
    files = load_repo_files(repo_files, default_path, templates_repo)
    return files, f"{templates_repo}:{default_path}"


def build_render_context(item: dict, metadata: dict, instance_id: str) -> dict:
    """Jinja context — identical rules to .ee-bench rendering.

    Starts from item fields, merges top-level metadata fields for missing
    keys (with the empty-expected replacement rule), then applies computed
    built-ins, which always win.
    """
    ctx = dict(item)

    for k, v in metadata.items():
        if not isinstance(v, (str, int, float, bool, list, dict)):
            continue
        should_fill_missing = k not in ctx
        should_replace_empty_expected = (
            k == "expected"
            and not _expected_has_tests(ctx.get("expected"))
            and _expected_has_tests(v)
        )
        if should_fill_missing or should_replace_empty_expected:
            ctx[k] = v

    owner = item.get("owner", "")
    repo_name = item.get("repo", "")
    ctx["owner"] = owner
    ctx["repo_name"] = repo_name
    ctx["repo"] = f"{owner}/{repo_name}" if owner else repo_name
    ctx["instance_id"] = instance_id
    ctx["project_root"] = (
        metadata.get("environment", {}).get("project_root")
        if isinstance(metadata.get("environment"), dict)
        else None
    ) or metadata.get("project_root") or "/repo"

    normalize_expected_fields(ctx)
    return ctx


def render_task_files(files: dict[str, TaskFile], ctx: dict) -> dict[str, TaskFile]:
    """Render every text file through Jinja; binary files pass through."""
    rendered: dict[str, TaskFile] = {}
    for rel_path, task_file in files.items():
        text = task_file.text()
        if text is None:
            rendered[rel_path] = task_file
            continue
        try:
            new_text = render_template(text, ctx)
        except Exception as exc:
            raise HarborExportError(f"Failed to render {rel_path}: {exc}")
        rendered[rel_path] = TaskFile(
            content=new_text.encode("utf-8"),
            executable=task_file.executable,
            origin=task_file.origin,
        )
    return rendered


def inject_datapoint_files(
    files: dict[str, TaskFile],
    *,
    problem_statement: str,
    gold_patch: str,
    test_patch: str,
) -> None:
    """Add per-datapoint files the export script owns (spec §3 table)."""
    if "instruction.md" not in files:
        text = problem_statement if problem_statement.endswith("\n") else problem_statement + "\n"
        files["instruction.md"] = TaskFile(content=text.encode("utf-8"), origin="injected")

    files["solution/patch.diff"] = TaskFile(content=gold_patch.encode("utf-8"), origin="injected")

    if "solution/solve.sh" not in files:
        files["solution/solve.sh"] = TaskFile(
            content=SOLVE_SH.encode("utf-8"), executable=True, origin="injected"
        )

    if test_patch.strip():
        files["tests/test_patch.diff"] = TaskFile(
            content=test_patch.encode("utf-8"), origin="injected"
        )


def post_render_checks(files: dict[str, TaskFile]) -> None:
    """task.toml must parse; no unrendered {{ instance.* }} markers remain."""
    task_toml = files.get("task.toml")
    if task_toml is None:
        raise HarborExportError("Merged Harbor task is missing task.toml")
    try:
        tomllib.loads(task_toml.text() or "")
    except tomllib.TOMLDecodeError as exc:
        raise HarborExportError(f"Rendered task.toml is not valid TOML: {exc}")

    unrendered = []
    for rel_path, task_file in sorted(files.items()):
        if task_file.origin == "injected":
            continue  # verbatim PR content (patches, instruction), never rendered
        text = task_file.text()
        if text is not None and UNRENDERED_MARKER_RE.search(text):
            unrendered.append(rel_path)
    if unrendered:
        raise HarborExportError(
            "Unrendered {{ instance.* }} markers remain in: " + ", ".join(unrendered)
        )


def write_task(files: dict[str, TaskFile], task_dir: Path) -> None:
    import shutil

    if task_dir.exists():
        shutil.rmtree(task_dir)
    for rel_path, task_file in files.items():
        rel = Path(rel_path)
        if rel.is_absolute() or ".." in rel.parts or rel_path in ("", "."):
            raise HarborExportError(f"Unsafe relative path in task files: {rel_path!r}")
        dest = task_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(task_file.content)
        if task_file.executable or rel_path in ALWAYS_EXECUTABLE:
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def fetch_pr_item(repo: str, pr_number: int, token: str) -> dict:
    from ee_bench.github import GitHubPullRequestsProvider

    github = GitHubPullRequestsProvider(token=token)
    filters = {"repo": repo, "pr_numbers": [pr_number]}
    for item in github.provide(filters=filters):
        return item
    raise HarborExportError(f"PR {repo}#{pr_number} not found")


def export(config: dict[str, str], output_dir: Path) -> int:
    from ee_bench.github.api import GitHubAPIClient
    from ee_bench.metadata import SectionProvider
    from ee_bench.patch_splitter import PatchSplitterProvider

    repo = config.get("REPO", "")
    pr_number = int(config.get("PR_NUMBER", "0") or "0")
    templates_repo = config.get("TEMPLATES_REPO") or DEFAULT_TEMPLATES_REPO
    templates_path = config.get("TEMPLATES_PATH") or DEFAULT_TEMPLATES_PATH
    if not repo or "/" not in repo or not pr_number:
        raise HarborExportError("REPO=<owner>/<name> and PR_NUMBER are required")

    token = os.environ["GITHUB_TOKEN"]
    client = GitHubAPIClient(token=token)

    default_branch_cache: dict[str, str] = {}

    def default_branch_of(repo_full: str) -> str:
        if repo_full not in default_branch_cache:
            try:
                data = client.get(f"/repos/{repo_full}")
            except Exception as exc:
                # An unreachable repo resolves to an empty tree downstream:
                # capability check treats it as "no default template", explicit
                # refs fail with a proper "does not resolve" error.
                logger.warning("Could not fetch default branch of %s: %s", repo_full, exc)
                data = {}
            default_branch_cache[repo_full] = data.get("default_branch", "main")
        return default_branch_cache[repo_full]

    # --- 1. Fetch PR data ---
    item = fetch_pr_item(repo, pr_number, token)
    source_org = item.get("owner", "")
    source_repo_name = item.get("repo", "")
    head_commit = item.get("head_commit", "")

    sections = SectionProvider(sections={
        "problem_statement": "## Problem Statement",
        "hints_text": "## Hints",
        "interface": "## Interface",
        "requirements": "## Requirements",
    })
    section_data = sections.provide(text=item.get("description", ""))
    problem_statement = strip_test_field_lines(
        section_data.get("problem_statement") or item.get("description", "")
    )

    pr_head = RepoFiles(client, source_org, source_repo_name, head_commit)
    source_default = RepoFiles(
        client, source_org, source_repo_name, default_branch_of(repo)
    )

    # --- 2. Resolve metadata (before the capability check: templates.harbor
    # participates in it) ---
    metadata_ctx = dict(item)
    metadata_ctx["owner"] = source_org
    metadata_ctx["repo_name"] = source_repo_name
    metadata_ctx["repo"] = repo
    metadata, metadata_source = resolve_metadata(pr_head, source_default, metadata_ctx)
    normalize_expected_fields(metadata)
    logger.info("Metadata resolved from %s", metadata_source)

    templates_map = metadata.get("templates")
    harbor_ref = templates_map.get("harbor") if isinstance(templates_map, dict) else None

    # --- 3. Capability check ---
    if harbor_ref is False:
        logger.info("templates.harbor is false — harbor format opted out")
        emit_output("harbor_status", "skipped")
        return 0

    pr_harbor_files = pr_head.subtree(HARBOR_DIR)
    has_explicit_ref = isinstance(harbor_ref, str)
    has_pr_overrides = bool(pr_harbor_files)
    has_default_template = False
    if not has_explicit_ref:
        tmpl_owner, _, tmpl_name = templates_repo.partition("/")
        templates_files = RepoFiles(
            client, tmpl_owner, tmpl_name, default_branch_of(templates_repo)
        )
        default_path = f"{templates_path.rstrip('/')}/{source_org}/{source_repo_name}"
        has_default_template = bool(templates_files.subtree(default_path))

    if not (has_explicit_ref or has_default_template or has_pr_overrides):
        logger.info(
            "Not harbor-capable: no templates.harbor ref, no central template, "
            "no .harbor/ in PR head — skipping"
        )
        emit_output("harbor_status", "skipped")
        return 0

    # --- 4. Merge template + PR .harbor/ overrides ---
    files, template_label = resolve_template_files(
        client,
        harbor_ref,
        templates_repo,
        templates_path,
        source_org,
        source_repo_name,
        default_branch_of,
    )
    logger.info("Template: %s (%d files)", template_label, len(files))

    overrides = load_repo_files(pr_head, HARBOR_DIR, f"{repo}#{pr_number}:.harbor")
    overrides.pop("metadata.json", None)  # data, not template
    for rel_path, task_file in overrides.items():
        files[rel_path] = task_file
    if overrides:
        logger.info("PR .harbor/ overrides: %s", ", ".join(sorted(overrides)))

    missing = [f for f in REQUIRED_TEMPLATE_FILES if f not in files]
    if missing:
        raise HarborExportError(
            "Merged Harbor task is missing required files: " + ", ".join(missing)
        )

    # --- 5. Split patches ---
    patch_cls = metadata.get("patch") or {}
    patch_data = PatchSplitterProvider().provide(
        patch=item.get("patch", ""),
        exclude_paths=[".ee-bench/", f"{HARBOR_DIR}/"],
        test_patterns=patch_cls.get("test_patterns"),
        source_patterns=patch_cls.get("source_patterns"),
    )
    gold_patch = patch_data.get("patch", "")
    test_patch = patch_data.get("test_patch", "")
    if not gold_patch.strip():
        raise HarborExportError(
            "Gold patch is empty after splitting (no non-test source changes in the PR)"
        )

    # --- 6. Render ---
    instance_id = metadata.get("instance_id") or derive_instance_id(item)
    ctx = build_render_context(item, metadata, instance_id)
    files = render_task_files(files, ctx)

    # --- 7. Inject per-datapoint files ---
    inject_datapoint_files(
        files,
        problem_statement=problem_statement,
        gold_patch=gold_patch,
        test_patch=test_patch,
    )

    # --- 8. Post-render checks ---
    post_render_checks(files)

    # --- 9. Write output ---
    language = metadata.get("language") or ctx.get("language")
    if not language:
        raise HarborExportError(
            f"metadata.json ({metadata_source}) is missing the 'language' field, "
            "required for the _harbor_converted/<language>/... layout"
        )

    task_rel = f"{language}/{source_repo_name}/{instance_id}"
    task_dir = output_dir / task_rel
    write_task(files, task_dir)
    logger.info("Wrote Harbor task: %s", task_dir)

    emit_output("harbor_status", "generated")
    emit_output("harbor_task_dir", str(task_dir))
    emit_output("harbor_task_rel", task_rel)
    emit_output("instance_id", str(instance_id))
    return 0


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
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Export option, compatible with export_unified.py "
        "(REPO, PR_NUMBER, TEMPLATES_REPO, TEMPLATES_PATH, OUTPUT_DIR).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory where the Harbor task directory is written "
        "(overrides --set OUTPUT_DIR).",
    )
    args = parser.parse_args()

    try:
        config = parse_set_flags(getattr(args, "set"))
        output_dir = args.output_dir or Path(
            config.get("OUTPUT_DIR") or DEFAULT_OUTPUT_DIR
        )
        return export(config, output_dir)
    except (HarborExportError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
