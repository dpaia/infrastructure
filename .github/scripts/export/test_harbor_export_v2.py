from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import export_datapoints_v2  # noqa: E402
import generate_manifest_v2  # noqa: E402
import resolve_instances_v2  # noqa: E402


def test_parse_instance_ids_splits_commas_and_newlines() -> None:
    assert resolve_instances_v2.parse_instance_ids("a,b\nc\n\n a ") == [
        "a",
        "b",
        "c",
    ]


def test_harbor_find_instance_dir_prefers_converted_over_manual(
    tmp_path: Path,
) -> None:
    converted = (
        tmp_path
        / "_harbor_converted"
        / "java"
        / "spring-petclinic"
        / "dpaia__spring__petclinic-132"
    )
    manual = (
        tmp_path / "_harbor_manual" / "_test_infra" / "dpaia__spring__petclinic-132"
    )
    converted.mkdir(parents=True)
    manual.mkdir(parents=True)
    (converted / "task.toml").write_text("name = 'converted'\n")
    (manual / "task.toml").write_text("name = 'manual'\n")

    result = export_datapoints_v2.find_instance_dir(
        "dpaia__spring__petclinic-132",
        "codegen",
        tmp_path,
        output_format="harbor",
    )

    assert result == converted


def test_harbor_glob_matches_manual_only_task(tmp_path: Path) -> None:
    manual = tmp_path / "_harbor_manual" / "_test_infra" / "dpaia__test_infra_java_1"
    manual.mkdir(parents=True)
    (manual / "task.toml").write_text("name = 'manual'\n")

    result = export_datapoints_v2.find_instance_dirs(
        "dpaia__test_infra_*",
        "codegen",
        tmp_path,
        "harbor",
    )

    assert result == [("dpaia__test_infra_java_1", manual)]


def test_harbor_glob_ignores_group_directories(tmp_path: Path) -> None:
    group = tmp_path / "_harbor_manual" / "_test_infra"
    task = group / "dpaia__test_infra_java_1"
    task.mkdir(parents=True)
    (task / "task.toml").write_text("name = 'manual'\n")

    result = export_datapoints_v2.find_instance_dirs(
        "*test_infra*",
        "codegen",
        tmp_path,
        "harbor",
    )

    assert result == [("dpaia__test_infra_java_1", task)]


def test_harbor_export_copies_task_dir_and_records_actual_id(tmp_path: Path) -> None:
    source = tmp_path / "dataset" / "_harbor_manual" / "_test_infra"
    task = source / "dpaia__test_infra_java_1"
    task.mkdir(parents=True)
    (task / "task.toml").write_text("name = 'manual'\n")
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("dpaia__test_infra_*\nmissing-task\n")
    output = tmp_path / "out"
    exported_ids = tmp_path / "exported.txt"
    skipped_ids = tmp_path / "skipped.txt"

    rc = export_datapoints_v2.main(
        [
            "--ids-file",
            str(ids_file),
            "--eval-type",
            "codegen",
            "--dataset-dir",
            str(tmp_path / "dataset"),
            "--format",
            "harbor",
            "--output-dir",
            str(output),
            "--exported-ids-file",
            str(exported_ids),
            "--skipped-ids-file",
            str(skipped_ids),
        ]
    )

    assert rc == 0
    assert (output / "dpaia__test_infra_java_1" / "task.toml").is_file()
    assert exported_ids.read_text() == "dpaia__test_infra_java_1\n"
    assert skipped_ids.read_text() == "missing-task\n"


def test_harbor_export_dedupes_overlapping_selectors(tmp_path: Path) -> None:
    source = tmp_path / "dataset" / "_harbor_manual" / "_test_infra"
    task = source / "dpaia__test_infra_java_1"
    task.mkdir(parents=True)
    (task / "task.toml").write_text("name = 'manual'\n")
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("dpaia__test_infra_java_1\ndpaia__test_infra_*\n")
    output = tmp_path / "out"
    exported_ids = tmp_path / "exported.txt"

    rc = export_datapoints_v2.main(
        [
            "--ids-file",
            str(ids_file),
            "--eval-type",
            "codegen",
            "--dataset-dir",
            str(tmp_path / "dataset"),
            "--format",
            "harbor",
            "--output-dir",
            str(output),
            "--exported-ids-file",
            str(exported_ids),
        ]
    )

    assert rc == 0
    assert exported_ids.read_text() == "dpaia__test_infra_java_1\n"


def test_generate_manifest_includes_harbor_fields(tmp_path: Path) -> None:
    exported_ids = tmp_path / "exported.txt"
    skipped_ids = tmp_path / "skipped.txt"
    exported_ids.write_text("task-a\n")
    skipped_ids.write_text("task-b\n")
    output = tmp_path / "out"

    rc = generate_manifest_v2.main(
        [
            "--exported-ids-file",
            str(exported_ids),
            "--eval-type",
            "codegen",
            "--format",
            "harbor",
            "--query",
            'label:"Language: C#"',
            "--dataset-commit",
            "abc123",
            "--skipped-ids-file",
            str(skipped_ids),
            "--output-dir",
            str(output),
        ]
    )

    assert rc == 0
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["format"] == "harbor"
    assert manifest["dataset_commit"] == "abc123"
    assert manifest["dataset_repo_commit"] == "abc123"
    assert manifest["matched_instance_ids"] == ["task-a"]
    assert manifest["skipped_instance_ids"] == ["task-b"]
