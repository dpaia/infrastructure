from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from eval_readiness.config import (
    EvalProjectsConfig,
    ReadinessConfig,
    ResolvedReadiness,
    load_eval_projects,
    load_readiness_config,
    resolve_readiness,
)
from eval_readiness.jsonl import JsonlError, dumps_jsonl, merge_by_instance_id, normalize_datapoint
from eval_readiness.start import parse_instance_id


class HfSyncError(RuntimeError):
    """Raised for sync failures that should leave private items queued for retry."""


class HfSyncItemError(ValueError):
    """Raised for item-specific data/config errors that can be marked failed."""


@dataclass(frozen=True, order=True)
class SourceKey:
    owner: str
    repo: str
    number: int

    @property
    def full_repo(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def display(self) -> str:
        return f"{self.full_repo}#{self.number}"


@dataclass(frozen=True)
class EvalMembership:
    eval_type: str
    project_number: str
    item_id: str


@dataclass(frozen=True, order=True)
class GroupKey:
    eval_type: str
    language_label: str
    hf_dataset: str
    hf_path: str

    @property
    def language_name(self) -> str:
        return self.language_label.removeprefix("Language: ")


@dataclass(frozen=True)
class SyncCandidate:
    source: SourceKey
    private_item_id: str
    public_item_id: str
    public_project_number: str
    data_url: str
    instance_id: str
    resolved: ResolvedReadiness

    @property
    def group_key(self) -> GroupKey:
        return GroupKey(
            eval_type=self.resolved.profile.eval_type,
            language_label=self.resolved.language.label,
            hf_dataset=self.resolved.profile.hf_dataset,
            hf_path=self.resolved.hf_path,
        )


@dataclass(frozen=True)
class SyncRecord:
    candidate: SyncCandidate
    record: Mapping[str, Any]


@dataclass(frozen=True)
class UploadedItem:
    private_item_id: str
    public_item_id: str
    public_project_number: str
    source_repo: str
    source_pr_number: int
    hf_dataset: str
    hf_path: str
    hf_commit_sha: str


@dataclass(frozen=True)
class FailedItem:
    private_item_id: str
    error: str
    public_item_id: str = ""
    public_project_number: str = ""
    source_repo: str = ""
    source_pr_number: int = 0


@dataclass(frozen=True)
class GroupSummary:
    eval_type: str
    language: str
    hf_dataset: str
    hf_path: str
    item_count: int
    output_record_count: int
    changed: bool
    hf_commit_sha: str
    commit_message: str


@dataclass(frozen=True)
class SyncResult:
    queued_count: int
    uploaded_items: Sequence[UploadedItem]
    failed_items: Sequence[FailedItem]
    groups: Sequence[GroupSummary]

    @property
    def changed_group_count(self) -> int:
        return sum(1 for group in self.groups if group.changed)

    @property
    def noop_group_count(self) -> int:
        return sum(1 for group in self.groups if not group.changed)


@dataclass(frozen=True)
class GitHubFileLocation:
    owner: str
    repo: str
    ref: str
    path: str

    @property
    def contents_api_url(self) -> str:
        quoted_path = quote(self.path, safe="/")
        quoted_ref = quote(self.ref, safe="")
        return f"https://api.github.com/repos/{self.owner}/{self.repo}/contents/{quoted_path}?ref={quoted_ref}"


def run_sync(
    *,
    queued_items: Sequence[Mapping[str, Any]],
    dataset_items: Sequence[Mapping[str, Any]],
    eval_items_by_type: Mapping[str, Sequence[Mapping[str, Any]]],
    eval_projects_config: EvalProjectsConfig,
    readiness_config: ReadinessConfig,
    run_key: str,
    label_fetcher: Callable[[SourceKey], Sequence[str]],
    record_fetcher: Callable[[str], Mapping[str, Any]],
    hf_client_factory: Callable[[], Any],
) -> SyncResult:
    candidates, failed_items = prepare_candidates(
        queued_items=queued_items,
        dataset_items=dataset_items,
        eval_items_by_type=eval_items_by_type,
        eval_projects_config=eval_projects_config,
        readiness_config=readiness_config,
        label_fetcher=label_fetcher,
    )
    grouped_records, record_failures = build_upload_groups(candidates, record_fetcher)
    failed_items.extend(record_failures)

    uploaded_items: list[UploadedItem] = []
    group_summaries: list[GroupSummary] = []
    if grouped_records:
        hf_client = hf_client_factory()
        uploaded_items, group_summaries = upload_groups(grouped_records, hf_client, run_key)

    return SyncResult(
        queued_count=len(queued_items),
        uploaded_items=uploaded_items,
        failed_items=failed_items,
        groups=group_summaries,
    )


def prepare_candidates(
    *,
    queued_items: Sequence[Mapping[str, Any]],
    dataset_items: Sequence[Mapping[str, Any]],
    eval_items_by_type: Mapping[str, Sequence[Mapping[str, Any]]],
    eval_projects_config: EvalProjectsConfig,
    readiness_config: ReadinessConfig,
    label_fetcher: Callable[[SourceKey], Sequence[str]],
) -> tuple[list[SyncCandidate], list[FailedItem]]:
    dataset_by_source = _index_by_source(dataset_items)
    eval_memberships = _index_eval_memberships(eval_items_by_type, eval_projects_config.eval_projects)

    candidates: list[SyncCandidate] = []
    failed: list[FailedItem] = []

    for item in queued_items:
        source: SourceKey | None = None
        membership: EvalMembership | None = None
        private_item_id = _item_id(item)
        try:
            source = _source_key(item)
            memberships = eval_memberships.get(source, [])
            if not memberships:
                raise HfSyncItemError(f"{source.display}: source PR was not found in a configured eval project")
            if len(memberships) > 1:
                eval_types = ", ".join(sorted(m.eval_type for m in memberships))
                raise HfSyncItemError(f"{source.display}: source PR is in multiple eval projects: {eval_types}")
            membership = memberships[0]

            dataset_item = dataset_by_source.get(source)
            if dataset_item is None:
                raise HfSyncItemError(f"{source.display}: source PR was not found in Dataset Metadata project")
            data_url = _field(dataset_item, "Data")
            if not data_url:
                raise HfSyncItemError(f"{source.display}: Dataset Metadata item has no Data URL")
            instance_id = parse_instance_id(data_url)
            if not instance_id:
                raise HfSyncItemError(f"{source.display}: could not parse instance id from Data URL: {data_url}")

            labels = label_fetcher(source)
            resolved = resolve_readiness(readiness_config, membership.eval_type, labels)
            if not isinstance(resolved, ResolvedReadiness):
                raise HfSyncItemError(f"{source.display}: {resolved.detail}")

            candidates.append(
                SyncCandidate(
                    source=source,
                    private_item_id=private_item_id,
                    public_item_id=membership.item_id,
                    public_project_number=membership.project_number,
                    data_url=data_url,
                    instance_id=instance_id,
                    resolved=resolved,
                )
            )
        except HfSyncItemError as exc:
            failed.append(_failed_item(private_item_id, str(exc), source, membership))

    return candidates, failed


def build_upload_groups(
    candidates: Sequence[SyncCandidate],
    record_fetcher: Callable[[str], Mapping[str, Any]],
) -> tuple[dict[GroupKey, list[SyncRecord]], list[FailedItem]]:
    grouped: dict[GroupKey, list[SyncRecord]] = defaultdict(list)
    failed: list[FailedItem] = []

    for candidate in candidates:
        try:
            record = record_fetcher(candidate.data_url)
            if not isinstance(record, Mapping):
                raise HfSyncItemError(f"{candidate.source.display}: dataset Data URL did not return a JSON object")
            normalized = normalize_datapoint(
                record,
                source_repo=candidate.source.full_repo,
                source_pr_number=candidate.source.number,
                instance_id=candidate.instance_id,
            )
            grouped[candidate.group_key].append(SyncRecord(candidate=candidate, record=normalized))
        except (HfSyncItemError, JsonlError) as exc:
            failed.append(_failed_item_from_candidate(candidate, str(exc)))

    return dict(grouped), failed


def upload_groups(
    grouped_records: Mapping[GroupKey, Sequence[SyncRecord]],
    hf_client: Any,
    run_key: str,
) -> tuple[list[UploadedItem], list[GroupSummary]]:
    uploaded: list[UploadedItem] = []
    summaries: list[GroupSummary] = []

    for group_key in sorted(grouped_records):
        records = list(grouped_records[group_key])
        existing_text, base_sha = hf_client.read_text(group_key.hf_dataset, group_key.hf_path)
        merged_records = merge_by_instance_id(
            existing_text.splitlines(keepends=True),
            [record.record for record in records],
        )
        merged_text = dumps_jsonl(merged_records)
        changed = merged_text != existing_text
        commit_message = _commit_message(group_key, len(records), run_key)
        if changed:
            hf_commit_sha = hf_client.write_text(
                group_key.hf_dataset,
                group_key.hf_path,
                merged_text,
                commit_message,
            )
        else:
            hf_commit_sha = base_sha

        summaries.append(
            GroupSummary(
                eval_type=group_key.eval_type,
                language=group_key.language_name,
                hf_dataset=group_key.hf_dataset,
                hf_path=group_key.hf_path,
                item_count=len(records),
                output_record_count=len(merged_records),
                changed=changed,
                hf_commit_sha=hf_commit_sha,
                commit_message=commit_message,
            )
        )
        for record in records:
            candidate = record.candidate
            uploaded.append(
                UploadedItem(
                    private_item_id=candidate.private_item_id,
                    public_item_id=candidate.public_item_id,
                    public_project_number=candidate.public_project_number,
                    source_repo=candidate.source.full_repo,
                    source_pr_number=candidate.source.number,
                    hf_dataset=group_key.hf_dataset,
                    hf_path=group_key.hf_path,
                    hf_commit_sha=hf_commit_sha,
                )
            )

    return uploaded, summaries


def parse_github_file_url(data_url: str) -> GitHubFileLocation:
    parsed = urlparse(data_url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc == "github.com" and len(parts) >= 5 and parts[2] in {"blob", "raw"}:
        return GitHubFileLocation(
            owner=parts[0],
            repo=parts[1],
            ref=parts[3],
            path="/".join(parts[4:]),
        )
    if parsed.netloc == "raw.githubusercontent.com" and len(parts) >= 4:
        return GitHubFileLocation(
            owner=parts[0],
            repo=parts[1],
            ref=parts[2],
            path="/".join(parts[3:]),
        )
    raise HfSyncItemError(f"unsupported dataset Data URL: {data_url}")


class GitHubClient:
    def __init__(self, token: str):
        self._token = token

    def get_pr_labels(self, source: SourceKey) -> list[str]:
        payload = self._request_json(
            f"https://api.github.com/repos/{source.owner}/{source.repo}/issues/{source.number}",
            accept="application/vnd.github+json",
        )
        labels = payload.get("labels", [])
        if not isinstance(labels, list):
            return []
        return [label["name"] for label in labels if isinstance(label, Mapping) and isinstance(label.get("name"), str)]

    def download_dataset_record(self, data_url: str) -> Mapping[str, Any]:
        location = parse_github_file_url(data_url)
        raw = self._request_bytes(location.contents_api_url, accept="application/vnd.github.raw+json")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HfSyncItemError(f"dataset Data URL does not contain valid JSON: {data_url}") from exc
        if not isinstance(payload, Mapping):
            raise HfSyncItemError(f"dataset Data URL did not return a JSON object: {data_url}")
        return payload

    def _request_json(self, url: str, *, accept: str) -> Mapping[str, Any]:
        raw = self._request_bytes(url, accept=accept)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HfSyncError(f"GitHub API returned invalid JSON: {url}") from exc
        if not isinstance(payload, Mapping):
            raise HfSyncError(f"GitHub API returned a non-object response: {url}")
        return payload

    def _request_bytes(self, url: str, *, accept: str) -> bytes:
        if not self._token:
            raise HfSyncError("GH_TOKEN is required")
        request = Request(
            url,
            headers={
                "Accept": accept,
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "eval-readiness-hf-sync",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code == 404:
                raise HfSyncItemError(f"GitHub URL returned 404: {url}") from exc
            raise HfSyncError(f"GitHub request failed with HTTP {exc.code}: {url}") from exc
        except URLError as exc:
            raise HfSyncError(f"GitHub request failed: {url}: {exc.reason}") from exc


class HfDatasetClient:
    def __init__(self, token: str):
        if not token:
            raise HfSyncError("HF_DATASET_TOKEN is required")
        self._token = token
        from huggingface_hub import HfApi

        self._api = HfApi(token=token)

    def read_text(self, dataset: str, path: str) -> tuple[str, str]:
        from huggingface_hub import hf_hub_download

        base_sha = self._repo_sha(dataset)
        try:
            local_path = hf_hub_download(
                repo_id=dataset,
                filename=path,
                repo_type="dataset",
                revision="main",
                token=self._token,
                force_download=True,
            )
        except Exception as exc:
            if _is_not_found_error(exc):
                return "", base_sha
            raise
        return Path(local_path).read_text(), base_sha

    def write_text(self, dataset: str, path: str, content: str, commit_message: str) -> str:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            commit_info = self._api.upload_file(
                path_or_fileobj=tmp_path,
                path_in_repo=path,
                repo_id=dataset,
                repo_type="dataset",
                commit_message=commit_message,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

        return _commit_sha(commit_info) or self._repo_sha(dataset)

    def _repo_sha(self, dataset: str) -> str:
        try:
            info = self._api.repo_info(repo_id=dataset, repo_type="dataset", revision="main")
        except Exception:
            return ""
        sha = getattr(info, "sha", "")
        return sha if isinstance(sha, str) else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch queued eval-readiness datapoints into stable HF JSONL files")
    parser.add_argument("--queued-items-file", type=Path, required=True)
    parser.add_argument("--dataset-items-file", type=Path, required=True)
    parser.add_argument("--eval-items-file", type=Path, required=True)
    parser.add_argument("--eval-projects-config", type=Path, default=Path(".github/config/eval-projects.json"))
    parser.add_argument("--readiness-config", type=Path, default=Path(".github/config/eval-readiness.json"))
    parser.add_argument("--run-key", default="manual")
    parser.add_argument("--github-token-env", default="GH_TOKEN")
    parser.add_argument("--hf-token-env", default="HF_DATASET_TOKEN")
    parser.add_argument("--github-output", type=Path, default=None)
    parser.add_argument("--summary-file", type=Path, default=None)
    args = parser.parse_args()

    github = GitHubClient(os.environ.get(args.github_token_env, ""))
    result = run_sync(
        queued_items=_read_json_array(args.queued_items_file),
        dataset_items=_read_json_array(args.dataset_items_file),
        eval_items_by_type=_read_eval_items(args.eval_items_file),
        eval_projects_config=load_eval_projects(args.eval_projects_config),
        readiness_config=load_readiness_config(args.readiness_config),
        run_key=args.run_key,
        label_fetcher=github.get_pr_labels,
        record_fetcher=github.download_dataset_record,
        hf_client_factory=lambda: HfDatasetClient(os.environ.get(args.hf_token_env, "")),
    )

    outputs = result_outputs(result)
    print(json.dumps(outputs, sort_keys=True))
    if args.github_output is not None:
        write_github_output(args.github_output, outputs)
    if args.summary_file is not None:
        args.summary_file.write_text(summary_markdown(result))
    return 0


def result_outputs(result: SyncResult) -> dict[str, str]:
    return {
        "uploaded_items": _json_compact([_uploaded_item_dict(item) for item in result.uploaded_items]),
        "uploaded_count": str(len(result.uploaded_items)),
        "failed_items": _json_compact([_failed_item_dict(item) for item in result.failed_items]),
        "failed_count": str(len(result.failed_items)),
        "groups": _json_compact([_group_summary_dict(group) for group in result.groups]),
        "group_count": str(len(result.groups)),
        "changed_group_count": str(result.changed_group_count),
        "noop_group_count": str(result.noop_group_count),
    }


def write_github_output(path: Path, outputs: Mapping[str, str]) -> None:
    with path.open("a") as output:
        for key, value in outputs.items():
            print(f"{key}={value}", file=output)


def summary_markdown(result: SyncResult) -> str:
    lines = [
        "# Eval-Readiness HF Sync Summary",
        "",
        f"- **Queued items:** {result.queued_count}",
        f"- **Uploaded/no-op items:** {len(result.uploaded_items)}",
        f"- **Failed items:** {len(result.failed_items)}",
        f"- **Changed groups:** {result.changed_group_count}",
        f"- **No-op groups:** {result.noop_group_count}",
        "",
    ]
    if result.groups:
        lines.extend(
            [
                "| Eval type | Language | HF path | Items | Changed | Commit SHA |",
                "| --- | --- | --- | ---: | --- | --- |",
            ]
        )
        for group in result.groups:
            lines.append(
                "| "
                + " | ".join(
                    [
                        group.eval_type,
                        group.language,
                        f"{group.hf_dataset}/{group.hf_path}",
                        str(group.item_count),
                        "yes" if group.changed else "no",
                        group.hf_commit_sha or "",
                    ]
                )
                + " |"
            )
        lines.append("")
    if result.failed_items:
        lines.extend(
            [
                "| Failed source | Error |",
                "| --- | --- |",
            ]
        )
        for item in result.failed_items:
            source = f"{item.source_repo}#{item.source_pr_number}" if item.source_repo else item.private_item_id
            lines.append(f"| {source} | {item.error} |")
        lines.append("")
    if not result.groups and not result.failed_items:
        lines.append("No queued items were ready for HF sync.")
    return "\n".join(lines) + "\n"


def _index_by_source(items: Sequence[Mapping[str, Any]]) -> dict[SourceKey, Mapping[str, Any]]:
    indexed: dict[SourceKey, Mapping[str, Any]] = {}
    for item in items:
        try:
            indexed[_source_key(item)] = item
        except HfSyncItemError:
            continue
    return indexed


def _index_eval_memberships(
    eval_items_by_type: Mapping[str, Sequence[Mapping[str, Any]]],
    eval_projects: Mapping[str, str],
) -> dict[SourceKey, list[EvalMembership]]:
    indexed: dict[SourceKey, list[EvalMembership]] = defaultdict(list)
    for eval_type, items in eval_items_by_type.items():
        project_number = eval_projects.get(eval_type)
        if not project_number:
            continue
        for item in items:
            try:
                source = _source_key(item)
            except HfSyncItemError:
                continue
            indexed[source].append(
                EvalMembership(
                    eval_type=eval_type,
                    project_number=project_number,
                    item_id=_item_id(item),
                )
            )
    return dict(indexed)


def _source_key(item: Mapping[str, Any]) -> SourceKey:
    owner = item.get("owner")
    repo = item.get("repo")
    number = item.get("number")
    if not isinstance(owner, str) or not owner:
        raise HfSyncItemError("project item has no owner")
    if not isinstance(repo, str) or not repo:
        raise HfSyncItemError("project item has no repo")
    return SourceKey(owner=owner, repo=repo, number=_coerce_positive_int(number, "project item number"))


def _coerce_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise HfSyncItemError(f"{name} must be a positive integer")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdecimal() and int(value) > 0:
        return int(value)
    raise HfSyncItemError(f"{name} must be a positive integer")


def _fields(item: Mapping[str, Any]) -> Mapping[str, Any]:
    fields = item.get("fields")
    return fields if isinstance(fields, Mapping) else {}


def _field(item: Mapping[str, Any], name: str) -> str:
    value = _fields(item).get(name)
    return value if isinstance(value, str) else ""


def _item_id(item: Mapping[str, Any]) -> str:
    item_id = item.get("item_id")
    return item_id if isinstance(item_id, str) else ""


def _failed_item(
    private_item_id: str,
    error: str,
    source: SourceKey | None,
    membership: EvalMembership | None,
) -> FailedItem:
    return FailedItem(
        private_item_id=private_item_id,
        error=_clean_error(error),
        public_item_id=membership.item_id if membership else "",
        public_project_number=membership.project_number if membership else "",
        source_repo=source.full_repo if source else "",
        source_pr_number=source.number if source else 0,
    )


def _failed_item_from_candidate(candidate: SyncCandidate, error: str) -> FailedItem:
    return FailedItem(
        private_item_id=candidate.private_item_id,
        error=_clean_error(error),
        public_item_id=candidate.public_item_id,
        public_project_number=candidate.public_project_number,
        source_repo=candidate.source.full_repo,
        source_pr_number=candidate.source.number,
    )


def _clean_error(error: str) -> str:
    return " ".join(error.split())[:500]


def _commit_message(group_key: GroupKey, count: int, run_key: str) -> str:
    return (
        f"Eval readiness {group_key.eval_type} {group_key.language_name}: "
        f"{count} datapoint(s) (run {run_key})"
    )


def _read_json_array(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError(f"{path}: expected JSON array")
    if not all(isinstance(item, Mapping) for item in payload):
        raise ValueError(f"{path}: expected array of JSON objects")
    return payload


def _read_eval_items(path: Path) -> dict[str, list[Mapping[str, Any]]]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path}: expected JSON object")
    result: dict[str, list[Mapping[str, Any]]] = {}
    for eval_type, items in payload.items():
        if not isinstance(eval_type, str):
            raise ValueError(f"{path}: eval type keys must be strings")
        if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
            raise ValueError(f"{path}: {eval_type} must be an array of JSON objects")
        result[eval_type] = items
    return result


def _json_compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _uploaded_item_dict(item: UploadedItem) -> dict[str, Any]:
    return {
        "private_item_id": item.private_item_id,
        "public_item_id": item.public_item_id,
        "public_project_number": item.public_project_number,
        "source_repo": item.source_repo,
        "source_pr_number": item.source_pr_number,
        "hf_dataset": item.hf_dataset,
        "hf_path": item.hf_path,
        "hf_commit_sha": item.hf_commit_sha,
    }


def _failed_item_dict(item: FailedItem) -> dict[str, Any]:
    return {
        "private_item_id": item.private_item_id,
        "public_item_id": item.public_item_id,
        "public_project_number": item.public_project_number,
        "source_repo": item.source_repo,
        "source_pr_number": item.source_pr_number,
        "error": item.error,
    }


def _group_summary_dict(group: GroupSummary) -> dict[str, Any]:
    return {
        "eval_type": group.eval_type,
        "language": group.language,
        "hf_dataset": group.hf_dataset,
        "hf_path": group.hf_path,
        "item_count": group.item_count,
        "output_record_count": group.output_record_count,
        "changed": group.changed,
        "hf_commit_sha": group.hf_commit_sha,
        "commit_message": group.commit_message,
    }


def _commit_sha(commit_info: Any) -> str:
    oid = getattr(commit_info, "oid", "")
    if isinstance(oid, str) and oid:
        return oid
    commit_url = getattr(commit_info, "commit_url", "")
    if isinstance(commit_url, str) and commit_url:
        return commit_url.rstrip("/").split("/")[-1]
    return ""


def _is_not_found_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 404:
        return True
    return exc.__class__.__name__ in {"EntryNotFoundError", "RemoteEntryNotFoundError"}


if __name__ == "__main__":
    raise SystemExit(main())
