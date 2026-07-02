import os
import stat

import pytest

from export_harbor_template import (
    HarborExportError,
    TaskFile,
    build_render_context,
    inject_datapoint_files,
    parse_template_ref,
    post_render_checks,
    render_task_files,
    resolve_metadata,
    write_task,
)


class FakeRepoFiles:
    """Stand-in for RepoFiles backed by an in-memory path->text map."""

    def __init__(self, files: dict[str, str]):
        self._files = files

    def read_text(self, path):
        return self._files.get(path)

    def read_bytes(self, path):
        content = self._files.get(path)
        return content.encode() if content is not None else None

    def subtree(self, prefix):
        prefix = prefix.rstrip("/") + "/"
        return {
            path[len(prefix):]: {"sha": "x", "mode": "100644"}
            for path in self._files
            if path.startswith(prefix)
        }


# --- parse_template_ref ---

def test_parse_template_ref_local_path():
    assert parse_template_ref("harbor/dpaia/feature-service@no-docker") == (
        None,
        "harbor/dpaia/feature-service@no-docker",
    )


def test_parse_template_ref_cross_repo():
    assert parse_template_ref("dpaia/other-templates:harbor/dpaia/feature-service") == (
        "dpaia/other-templates",
        "harbor/dpaia/feature-service",
    )


def test_parse_template_ref_rejects_bad_repo():
    with pytest.raises(HarborExportError):
        parse_template_ref("not-a-repo:harbor/x")


def test_parse_template_ref_rejects_traversal():
    with pytest.raises(HarborExportError):
        parse_template_ref("harbor/../secrets")


# --- resolve_metadata fallback chain ---

def test_resolve_metadata_prefers_pr_harbor_metadata():
    pr = FakeRepoFiles({
        ".harbor/metadata.json": '{"language": "java", "expected": {"fail_to_pass": ["T#a"]}}',
        ".ee-bench/codegen/metadata.json": '{"language": "kotlin"}',
    })
    default = FakeRepoFiles({".ee-bench/codegen/metadata.json": '{"language": "python"}'})
    metadata, source = resolve_metadata(pr, default, {})
    assert metadata["language"] == "java"
    assert source == ".harbor/metadata.json"


def test_resolve_metadata_ee_bench_deep_merge_pr_wins():
    pr = FakeRepoFiles({
        ".ee-bench/codegen/metadata.json": '{"expected": {"fail_to_pass": ["T#a"]}}',
    })
    default = FakeRepoFiles({
        ".ee-bench/codegen/metadata.json":
            '{"language": "java", "templates": {"harbor": "harbor/dpaia/x@v"}, '
            '"expected": {"pass_to_pass": ["T#b"]}}',
    })
    metadata, source = resolve_metadata(pr, default, {})
    assert source == ".ee-bench/codegen/metadata.json"
    # PR keys win, default-branch keys survive the deep merge
    assert metadata["expected"]["fail_to_pass"] == ["T#a"]
    assert metadata["expected"]["pass_to_pass"] == ["T#b"]
    assert metadata["language"] == "java"
    assert metadata["templates"]["harbor"] == "harbor/dpaia/x@v"


def test_resolve_metadata_renders_jinja_before_parse():
    pr = FakeRepoFiles({
        ".harbor/metadata.json": '{"instance_id": "{{ instance.repo_name }}-1"}',
    })
    metadata, _ = resolve_metadata(pr, FakeRepoFiles({}), {"repo_name": "svc"})
    assert metadata["instance_id"] == "svc-1"


def test_resolve_metadata_invalid_harbor_metadata_is_hard_error():
    pr = FakeRepoFiles({".harbor/metadata.json": "not json"})
    with pytest.raises(HarborExportError):
        resolve_metadata(pr, FakeRepoFiles({}), {})


# --- render context ---

def _item():
    return {
        "owner": "dpaia",
        "repo": "feature-service",
        "number": 42,
        "repo_url": "https://github.com/dpaia/feature-service.git",
        "base_commit": "base123",
        "head_commit": "head456",
        "description": "text",
        "FAIL_TO_PASS": "",
        "PASS_TO_PASS": "",
    }


def test_build_render_context_builtins_win_over_metadata():
    ctx = build_render_context(
        _item(),
        {"repo": "evil/override", "owner": "evil", "language": "java"},
        "dpaia__feature__service-42",
    )
    assert ctx["repo"] == "dpaia/feature-service"
    assert ctx["owner"] == "dpaia"
    assert ctx["repo_name"] == "feature-service"
    assert ctx["language"] == "java"
    assert ctx["instance_id"] == "dpaia__feature__service-42"
    assert ctx["project_root"] == "/repo"


def test_build_render_context_project_root_from_metadata_environment():
    ctx = build_render_context(
        _item(), {"environment": {"project_root": "/repo/app"}}, "id-1"
    )
    assert ctx["project_root"] == "/repo/app"


def test_build_render_context_metadata_expected_fills_in():
    ctx = build_render_context(
        _item(), {"expected": {"fail_to_pass": ["T#a"], "pass_to_pass": []}}, "id-1"
    )
    assert ctx["expected"]["fail_to_pass"] == ["T#a"]


def test_build_render_context_pr_body_tests_used_when_metadata_empty():
    item = _item()
    item["FAIL_TO_PASS"] = '["T#fromBody"]'
    ctx = build_render_context(
        item, {"expected": {"fail_to_pass": [], "pass_to_pass": []}}, "id-1"
    )
    assert ctx["expected"]["fail_to_pass"] == ["T#fromBody"]


# --- rendering ---

def test_render_task_files_renders_text_passes_binary():
    files = {
        "task.toml": TaskFile(content=b'name = "{{ instance.instance_id }}"'),
        "environment/blob.bin": TaskFile(content=b"\xff\xfe\x00\x01"),
        "tests/plain.txt": TaskFile(content=b"no markers here"),
    }
    rendered = render_task_files(files, {"instance_id": "abc-1"})
    assert rendered["task.toml"].content == b'name = "abc-1"'
    assert rendered["environment/blob.bin"].content == b"\xff\xfe\x00\x01"
    assert rendered["tests/plain.txt"].content == b"no markers here"


def test_render_task_files_tojson_filter():
    files = {
        "run.sh": TaskFile(content=b"F={{ instance.expected.fail_to_pass | tojson }}"),
    }
    rendered = render_task_files(files, {"expected": {"fail_to_pass": ["a", "b"]}})
    assert rendered["run.sh"].content == b'F=["a", "b"]'


# --- injection ---

def test_inject_datapoint_files_defaults():
    files = {}
    inject_datapoint_files(
        files, problem_statement="Fix it", gold_patch="diff --git a/x b/x\n", test_patch=""
    )
    assert files["instruction.md"].content == b"Fix it\n"
    assert files["solution/patch.diff"].content == b"diff --git a/x b/x\n"
    assert files["solution/solve.sh"].executable
    assert b"cd /repo\n" in files["solution/solve.sh"].content
    assert "tests/test_patch.diff" not in files


def test_inject_datapoint_files_solve_sh_uses_project_root():
    files = {}
    inject_datapoint_files(
        files,
        problem_statement="Fix it",
        gold_patch="gold\n",
        test_patch="",
        project_root="/repo/app",
    )
    assert b"cd /repo/app\n" in files["solution/solve.sh"].content


def test_inject_datapoint_files_respects_overrides_where_allowed():
    files = {
        "instruction.md": TaskFile(content=b"explicit"),
        "solution/solve.sh": TaskFile(content=b"custom", executable=True),
        "solution/patch.diff": TaskFile(content=b"stale"),
    }
    inject_datapoint_files(
        files, problem_statement="ignored", gold_patch="gold\n", test_patch="tests\n"
    )
    # explicit file wins for instruction.md and solve.sh
    assert files["instruction.md"].content == b"explicit"
    assert files["solution/solve.sh"].content == b"custom"
    # patch.diff and test_patch.diff are never overridable
    assert files["solution/patch.diff"].content == b"gold\n"
    assert files["tests/test_patch.diff"].content == b"tests\n"


# --- post-render checks ---

def _valid_files():
    return {
        "task.toml": TaskFile(content=b'schema_version = "1.3"\n'),
        "environment/Dockerfile": TaskFile(content=b"FROM scratch\n"),
        "tests/test.sh": TaskFile(content=b"#!/bin/bash\n", executable=True),
    }


def test_post_render_checks_pass():
    post_render_checks(_valid_files())


def test_post_render_checks_invalid_toml():
    files = _valid_files()
    files["task.toml"] = TaskFile(content=b"schema_version = \n")
    with pytest.raises(HarborExportError, match="not valid TOML"):
        post_render_checks(files)


def test_post_render_checks_unrendered_marker():
    files = _valid_files()
    files["environment/Dockerfile"] = TaskFile(
        content=b"FROM x\nRUN git checkout {{ instance.base_commit }}\n"
    )
    with pytest.raises(HarborExportError, match="environment/Dockerfile"):
        post_render_checks(files)


def test_post_render_checks_ignores_injected_files():
    files = _valid_files()
    files["solution/patch.diff"] = TaskFile(
        content=b"+eval {{ instance.base_commit }}\n", origin="injected"
    )
    post_render_checks(files)


# --- writing ---

def test_write_task_layout_and_exec_bits(tmp_path):
    files = _valid_files()
    files["solution/solve.sh"] = TaskFile(content=b"#!/bin/bash\n")
    task_dir = tmp_path / "java" / "feature-service" / "id-1"
    write_task(files, task_dir)

    assert (task_dir / "task.toml").read_bytes() == b'schema_version = "1.3"\n'
    assert (task_dir / "environment" / "Dockerfile").is_file()
    for exec_path in ("tests/test.sh", "solution/solve.sh"):
        mode = os.stat(task_dir / exec_path).st_mode
        assert mode & stat.S_IXUSR, f"{exec_path} should be executable"


def test_write_task_rejects_traversal(tmp_path):
    files = {"../escape": TaskFile(content=b"x")}
    with pytest.raises(HarborExportError):
        write_task(files, tmp_path / "task")


def test_write_task_overwrites_existing(tmp_path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "stale.txt").write_text("old")
    write_task(_valid_files(), task_dir)
    assert not (task_dir / "stale.txt").exists()
    assert (task_dir / "task.toml").is_file()
