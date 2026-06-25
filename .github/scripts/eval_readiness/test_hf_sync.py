import json
from collections.abc import Mapping
from typing import Any

from eval_readiness.config import EvalProjectsConfig, LanguageMapping, ReadinessConfig, ReadinessProfile
from eval_readiness.hf_sync import (
    GitHubFileLocation,
    parse_github_file_url,
    result_outputs,
    run_sync,
)
from eval_readiness.jsonl import dumps_jsonl, normalize_datapoint


def test_parse_github_file_url_from_blob_permalink() -> None:
    location = parse_github_file_url(
        "https://github.com/dpaia/dataset/blob/main/codegen/repo/dpaia__repo-1.json"
    )

    assert location == GitHubFileLocation(
        owner="dpaia",
        repo="dataset",
        ref="main",
        path="codegen/repo/dpaia__repo-1.json",
    )
    assert (
        location.contents_api_url
        == "https://api.github.com/repos/dpaia/dataset/contents/codegen/repo/dpaia__repo-1.json?ref=main"
    )


def test_run_sync_batches_two_java_items_into_one_hf_write() -> None:
    hf_client = FakeHfClient({})

    result = run_sync(
        queued_items=[
            _item("PVTI_private_1", "Kavita", 36),
            _item("PVTI_private_2", "Kavita", 37),
        ],
        dataset_items=[
            _item(
                "PVTI_dataset_1",
                "Kavita",
                36,
                fields={"Data": "https://github.com/dpaia/dataset/blob/main/codegen/Kavita/kavita-36.json"},
            ),
            _item(
                "PVTI_dataset_2",
                "Kavita",
                37,
                fields={"Data": "https://github.com/dpaia/dataset/blob/main/codegen/Kavita/kavita-37.json"},
            ),
        ],
        eval_items_by_type={
            "codegen": [
                _item("PVTI_public_1", "Kavita", 36),
                _item("PVTI_public_2", "Kavita", 37),
            ]
        },
        eval_projects_config=_eval_projects_config(),
        readiness_config=_readiness_config(),
        run_key="run-123",
        label_fetcher=lambda _: ["Language: Java"],
        record_fetcher=lambda url: {"prompt": url.rsplit("/", 1)[-1], "keep": True},
        hf_client_factory=lambda: hf_client,
    )

    assert len(result.failed_items) == 0
    assert len(result.uploaded_items) == 2
    assert len(result.groups) == 1
    assert result.groups[0].changed is True
    assert result.groups[0].commit_message == "Eval readiness codegen Java: 2 datapoint(s) (run run-123)"
    assert result.groups[0].hf_path == "code-generation-swe/java/dpai-java-instances.large"
    assert len(hf_client.writes) == 1

    written = hf_client.writes[0]
    assert written["dataset"] == "JetBrains/eval_plugin"
    assert written["path"] == "code-generation-swe/java/dpai-java-instances.large"
    records = [json.loads(line) for line in written["content"].splitlines()]
    assert records == [
        {
            "instance_id": "kavita-36",
            "keep": True,
            "pr_number": 36,
            "prompt": "kavita-36.json",
            "repo": "dpaia/Kavita",
            "source_pr_number": 36,
            "source_repo": "dpaia/Kavita",
        },
        {
            "instance_id": "kavita-37",
            "keep": True,
            "pr_number": 37,
            "prompt": "kavita-37.json",
            "repo": "dpaia/Kavita",
            "source_pr_number": 37,
            "source_repo": "dpaia/Kavita",
        },
    ]


def test_run_sync_treats_current_hf_content_as_successful_noop() -> None:
    data_url = "https://github.com/dpaia/dataset/blob/main/codegen/Kavita/kavita-36.json"
    record = normalize_datapoint(
        {"prompt": "same"},
        source_repo="dpaia/Kavita",
        source_pr_number=36,
        instance_id="kavita-36",
    )
    hf_client = FakeHfClient(
        {("JetBrains/eval_plugin", "code-generation-swe/java/dpai-java-instances.large"): dumps_jsonl([record])}
    )

    result = run_sync(
        queued_items=[_item("PVTI_private_1", "Kavita", 36)],
        dataset_items=[_item("PVTI_dataset_1", "Kavita", 36, fields={"Data": data_url})],
        eval_items_by_type={"codegen": [_item("PVTI_public_1", "Kavita", 36)]},
        eval_projects_config=_eval_projects_config(),
        readiness_config=_readiness_config(),
        run_key="run-123",
        label_fetcher=lambda _: ["Language: Java"],
        record_fetcher=lambda _: {"prompt": "same"},
        hf_client_factory=lambda: hf_client,
    )

    assert len(hf_client.writes) == 0
    assert len(result.uploaded_items) == 1
    assert result.uploaded_items[0].hf_commit_sha == "base-sha"
    assert result.groups[0].changed is False


def test_run_sync_marks_missing_dataset_item_failed_without_hf_client() -> None:
    result = run_sync(
        queued_items=[_item("PVTI_private_1", "Kavita", 36)],
        dataset_items=[],
        eval_items_by_type={"codegen": [_item("PVTI_public_1", "Kavita", 36)]},
        eval_projects_config=_eval_projects_config(),
        readiness_config=_readiness_config(),
        run_key="run-123",
        label_fetcher=lambda _: ["Language: Java"],
        record_fetcher=lambda _: {"prompt": "unused"},
        hf_client_factory=lambda: (_ for _ in ()).throw(AssertionError("HF client should not be created")),
    )

    assert len(result.uploaded_items) == 0
    assert len(result.failed_items) == 1
    assert result.failed_items[0].private_item_id == "PVTI_private_1"
    assert result.failed_items[0].public_item_id == "PVTI_public_1"
    assert "Dataset Metadata project" in result.failed_items[0].error


def test_result_outputs_are_compact_matrix_json() -> None:
    result = run_sync(
        queued_items=[_item("PVTI_private_1", "Kavita", 36)],
        dataset_items=[],
        eval_items_by_type={"codegen": [_item("PVTI_public_1", "Kavita", 36)]},
        eval_projects_config=_eval_projects_config(),
        readiness_config=_readiness_config(),
        run_key="run-123",
        label_fetcher=lambda _: ["Language: Java"],
        record_fetcher=lambda _: {"prompt": "unused"},
        hf_client_factory=lambda: (_ for _ in ()).throw(AssertionError("HF client should not be created")),
    )

    outputs = result_outputs(result)

    assert outputs["uploaded_items"] == "[]"
    assert outputs["uploaded_count"] == "0"
    assert outputs["failed_count"] == "1"
    assert json.loads(outputs["failed_items"])[0]["private_item_id"] == "PVTI_private_1"


class FakeHfClient:
    def __init__(self, files: Mapping[tuple[str, str], str]):
        self.files = dict(files)
        self.writes: list[dict[str, str]] = []

    def read_text(self, dataset: str, path: str) -> tuple[str, str]:
        return self.files.get((dataset, path), ""), "base-sha"

    def write_text(self, dataset: str, path: str, content: str, commit_message: str) -> str:
        self.files[(dataset, path)] = content
        self.writes.append(
            {
                "dataset": dataset,
                "path": path,
                "content": content,
                "commit_message": commit_message,
            }
        )
        return f"commit-sha-{len(self.writes)}"


def _item(item_id: str, repo: str, number: int, fields: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "content_type": "PullRequest",
        "owner": "dpaia",
        "repo": repo,
        "number": number,
        "fields": dict(fields or {}),
    }


def _eval_projects_config() -> EvalProjectsConfig:
    return EvalProjectsConfig(
        organization="dpaia",
        dataset_metadata_project="3",
        eval_readiness_project="17",
        eval_projects={"codegen": "13", "methodgen": "16"},
    )


def _readiness_config() -> ReadinessConfig:
    return ReadinessConfig(
        profiles={
            "codegen": ReadinessProfile(
                eval_type="codegen",
                enabled=True,
                hf_dataset="JetBrains/eval_plugin",
                hf_base_path="code-generation-swe",
                generator_kind="dpai-generic-format",
                registration_bucket="swe/dataset/dev",
            )
        },
        languages={
            "Language: Java": LanguageMapping(
                label="Language: Java",
                hf_dir="java",
                hf_filename="dpai-java-instances.large",
                pipeline_language_enum="JAVA",
                teamcity_dataset_id="Dpai-Bench",
            )
        },
    )
