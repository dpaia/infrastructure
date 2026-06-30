#!/usr/bin/env python3
"""Render Harbor task directories from EE-Bench codegen unified records."""

from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path
from typing import Any, Mapping


DEFAULT_CPUS = 2
DEFAULT_MEMORY_MB = 4096
DEFAULT_STORAGE_MB = 8192
DEFAULT_AGENT_TIMEOUT_SEC = 1800
DEFAULT_VERIFIER_TIMEOUT_SEC = 600
DEFAULT_BUILD_TIMEOUT_SEC = 1200


TEST_WRAPPER = """#!/usr/bin/env bash
set -uo pipefail

mkdir -p /logs/verifier /ee-bench/eval/scripts /ee-bench/submission

PROJECT_ROOT="${EE_BENCH_PROJECT_ROOT:-/repo}"
export EE_BENCH_PROJECT_ROOT="$PROJECT_ROOT"

cp /tests/scripts/run.sh /ee-bench/eval/run.sh
cp /tests/scripts/ee_bench_*.py /ee-bench/eval/scripts/ 2>/dev/null || true
if [ -f /tests/test_patch.diff ]; then
  cp /tests/test_patch.diff /ee-bench/eval/test_patch.diff
fi

cd "$PROJECT_ROOT" || {
  printf '{"schema_version":"2.0","status":"failure","criteria":[{"criterion":"project_root","status":"fail"}]}\\n' > /logs/verifier/result.json
  python3 /tests/scripts/ee_bench_to_reward.py /logs/verifier/result.json /logs/verifier/reward.txt /logs/verifier/reward.json
  exit 0
}

if git rev-parse --git-dir >/dev/null 2>&1; then
  git add -N . >/tmp/harbor_git_add_intent.log 2>&1 || true
  git diff --binary --no-ext-diff HEAD -- . ':(exclude).ee-bench/**' > /ee-bench/submission/patch.diff || true
  if [ ! -s /ee-bench/submission/patch.diff ]; then
    rm -f /ee-bench/submission/patch.diff
  fi
fi

EE_BENCH_RESET=1 bash /ee-bench/eval/run.sh > /logs/verifier/result.json 2>/logs/verifier/eval.err || true

python3 /tests/scripts/ee_bench_to_reward.py \\
  /logs/verifier/result.json \\
  /logs/verifier/reward.txt \\
  /logs/verifier/reward.json
"""


REWARD_ADAPTER = """#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def _status_score(status):
    if status == "pass":
        return 1.0
    if status == "fail":
        return 0.0
    return None


def _tests_passed_ratio(criteria):
    tests = criteria.get("tests", {})
    summary = tests.get("summary") or {}
    total = summary.get("total") or 0
    if not total:
        return _status_score(tests.get("status"))
    return float(summary.get("passed", 0)) / float(total)


def main():
    result_path = Path(sys.argv[1])
    reward_txt_path = Path(sys.argv[2])
    reward_json_path = Path(sys.argv[3])

    try:
        result = json.loads(result_path.read_text())
    except Exception:
        result = {"status": "failure", "criteria": []}

    criteria = {
        item.get("criterion"): item
        for item in result.get("criteria", [])
        if isinstance(item, dict) and item.get("criterion")
    }

    reward = 1.0 if result.get("status") == "success" else 0.0
    rewards = {"reward": reward}

    for name in (
        "compilation",
        "baseline_tests",
        "patch_applied",
        "tests",
        "fail_to_pass",
        "pass_to_pass",
        "spotless",
    ):
        score = _status_score(criteria.get(name, {}).get("status"))
        if score is not None:
            rewards[name] = score

    tests_ratio = _tests_passed_ratio(criteria)
    if tests_ratio is not None:
        rewards["tests_passed_ratio"] = tests_ratio

    reward_txt_path.write_text(f"{reward}\\n")
    reward_json_path.write_text(json.dumps(rewards, sort_keys=True) + "\\n")


if __name__ == "__main__":
    main()
"""


SOLVE_SH = """#!/usr/bin/env bash
set -euo pipefail

cd "${EE_BENCH_PROJECT_ROOT:-/repo}"
git apply /solution/patch.diff
"""


def emit_harbor_task(
    unified_record: Mapping[str, Any],
    out_dir: str | Path,
    *,
    source_dir: str | Path | None = None,
    overwrite: bool = True,
) -> None:
    """Write one Harbor task directory from a unified EE-Bench record.

    ``source_dir`` should point at the unified instance directory when
    ``datapoint.json`` contains relative file paths instead of inline content.
    """

    task_dir = Path(out_dir)
    if task_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Output task directory already exists: {task_dir}")
        shutil.rmtree(task_dir)

    source_path = Path(source_dir) if source_dir is not None else None
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "solution").mkdir()
    (task_dir / "tests" / "scripts").mkdir(parents=True)

    _write_text(
        task_dir / "instruction.md",
        _ensure_trailing_newline(str(unified_record.get("problem_statement", ""))),
    )
    _write_text(task_dir / "task.toml", render_task_toml(unified_record))

    _copy_environment_files(unified_record, source_path, task_dir / "environment")
    _copy_eval_files(unified_record, source_path, task_dir / "tests")
    _copy_solution_files(unified_record, source_path, task_dir / "solution")

    _write_executable(task_dir / "tests" / "test.sh", TEST_WRAPPER)
    _write_executable(task_dir / "tests" / "scripts" / "ee_bench_to_reward.py", REWARD_ADAPTER)
    _write_executable(task_dir / "solution" / "solve.sh", SOLVE_SH)


def render_task_toml(record: Mapping[str, Any]) -> str:
    env = _as_mapping(record.get("environment"))
    expected = _as_mapping(record.get("expected"))
    resources = _as_mapping(env.get("resources"))
    timeouts = _as_mapping(env.get("timeouts"))
    run_params = _as_mapping(_as_mapping(env.get("docker")).get("run_params"))

    network_mode = str(env.get("network_mode") or _network_from_run_params(run_params))
    allowed_hosts = list(env.get("allowed_hosts") or [])
    environment_values = _string_map(run_params.get("environment"))

    metadata = {
        "instance_id": record.get("instance_id", ""),
        "repo": record.get("repo", ""),
        "base_commit": record.get("base_commit", ""),
        "benchmark_type": record.get("benchmark_type", "codegen"),
        "language": record.get("language", ""),
        "jvm_version": record.get("jvm_version", ""),
        "build_system": record.get("build_system", ""),
        "issue_numbers": _issue_numbers(record),
        "fail_to_pass": _list_of_strings(expected.get("fail_to_pass")),
        "pass_to_pass": _list_of_strings(expected.get("pass_to_pass")),
    }

    task = {
        "name": _harbor_task_name(record),
        "description": _description(record),
        "keywords": _list_of_strings(record.get("tags")),
    }

    environment = {
        "cpus": _int_or_default(resources.get("cpus"), DEFAULT_CPUS),
        "memory_mb": _int_or_default(resources.get("memory_mb"), DEFAULT_MEMORY_MB),
        "storage_mb": _int_or_default(resources.get("storage_mb"), DEFAULT_STORAGE_MB),
        "network_mode": network_mode,
        "build_timeout_sec": _int_or_default(
            timeouts.get("build_seconds"), DEFAULT_BUILD_TIMEOUT_SEC
        ),
        "workdir": str(env.get("project_root") or record.get("project_root") or "/repo"),
    }
    if network_mode == "allowlist":
        environment["allowed_hosts"] = _list_of_strings(allowed_hosts)

    parts = [
        _toml_table(None, {"schema_version": "1.3"}),
        _toml_table("task", task),
        _toml_table("metadata", metadata),
        _toml_table("environment", environment),
    ]
    if environment_values:
        parts.append(_toml_table("environment.env", environment_values))
    parts.extend(
        [
            _toml_table(
                "agent",
                {
                    "timeout_sec": _int_or_default(
                        timeouts.get("agent_seconds"), DEFAULT_AGENT_TIMEOUT_SEC
                    )
                },
            ),
            _toml_table(
                "verifier",
                {
                    "timeout_sec": _int_or_default(
                        timeouts.get("verifier_seconds"), DEFAULT_VERIFIER_TIMEOUT_SEC
                    ),
                    "environment_mode": "shared",
                },
            ),
        ]
    )
    return "\n\n".join(part for part in parts if part).rstrip() + "\n"


def _copy_environment_files(record: Mapping[str, Any], source_dir: Path | None, dest: Path) -> None:
    files = _files(record, "environment")
    if "Dockerfile" not in files:
        raise ValueError("Unified record is missing environment.files.Dockerfile")
    for logical_name in sorted(files):
        _write_bytes(dest / _safe_relative_path(logical_name), _file_bytes(files[logical_name], source_dir))


def _copy_eval_files(record: Mapping[str, Any], source_dir: Path | None, tests_dir: Path) -> None:
    files = _files(record, "eval")
    if "run.sh" not in files:
        raise ValueError("Unified record is missing eval.files.run.sh")
    for logical_name in sorted(files):
        data = _file_bytes(files[logical_name], source_dir)
        if logical_name == "test_patch.diff":
            _write_bytes(tests_dir / "test_patch.diff", data)
        else:
            dest_name = logical_name.removeprefix("scripts/")
            _write_bytes(tests_dir / "scripts" / _safe_relative_path(dest_name), data)


def _copy_solution_files(record: Mapping[str, Any], source_dir: Path | None, solution_dir: Path) -> None:
    files = _files(record, "verify")
    patch_name = "patch.diff"
    if patch_name not in files:
        raise ValueError("Unified record is missing verify.files.patch.diff")
    _write_bytes(solution_dir / patch_name, _file_bytes(files[patch_name], source_dir))


def _files(record: Mapping[str, Any], section: str) -> Mapping[str, Any]:
    section_data = _as_mapping(record.get(section))
    files = section_data.get("files")
    if not isinstance(files, Mapping):
        raise ValueError(f"Unified record is missing {section}.files")
    return files


def _file_bytes(value: Any, source_dir: Path | None) -> bytes:
    if isinstance(value, str) and source_dir is not None:
        candidate = source_dir / value
        if candidate.is_file():
            return candidate.read_bytes()
    if isinstance(value, bytes):
        return value
    return str(value).encode()


def _safe_relative_path(path: str) -> Path:
    rel = Path(path)
    if rel.is_absolute() or ".." in rel.parts or path in ("", "."):
        raise ValueError(f"Unsafe relative file path in record: {path!r}")
    return rel


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_executable(path: Path, text: str) -> None:
    _write_text(path, text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _ensure_trailing_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def _description(record: Mapping[str, Any]) -> str:
    explicit = record.get("description")
    if explicit:
        return str(explicit).strip()
    for line in str(record.get("problem_statement", "")).splitlines():
        if line.strip():
            return line.strip()
    return str(record.get("instance_id", "EE-Bench codegen task"))


def _harbor_task_name(record: Mapping[str, Any]) -> str:
    instance_id = str(record.get("instance_id") or "unnamed")
    repo = str(record.get("repo") or "")
    org = repo.split("/", 1)[0] if "/" in repo else "ee-bench"
    return f"{org}/{instance_id}"


def _issue_numbers(record: Mapping[str, Any]) -> list[str]:
    if record.get("issue_numbers"):
        return _list_of_strings(record.get("issue_numbers"))
    if record.get("pr_number") not in (None, ""):
        return [str(record["pr_number"])]
    return []


def _network_from_run_params(run_params: Mapping[str, Any]) -> str:
    if str(run_params.get("network") or "").lower() == "none":
        return "no-network"
    return "public"


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(k): str(v) for k, v in value.items()}


def _list_of_strings(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _toml_table(name: str | None, values: Mapping[str, Any]) -> str:
    lines = []
    if name is not None:
        lines.append(f"[{name}]")
    for key, value in values.items():
        if value in (None, ""):
            continue
        lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    return json.dumps(str(value))
