from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any


class JsonlError(ValueError):
    """Raised when eval-readiness JSONL input is invalid."""


def normalize_datapoint(
    record: Mapping[str, Any],
    source_repo: str,
    source_pr_number: int | str,
    instance_id: str,
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise JsonlError("datapoint record must be an object")
    if not source_repo:
        raise JsonlError("source_repo must be non-empty")
    if not instance_id:
        raise JsonlError("instance_id must be non-empty")
    pr_number = _coerce_positive_int(source_pr_number, "source_pr_number")

    normalized = dict(record)
    normalized["instance_id"] = instance_id
    normalized["repo"] = source_repo
    normalized["pr_number"] = pr_number
    normalized["source_repo"] = source_repo
    normalized["source_pr_number"] = pr_number
    return normalized


def merge_by_instance_id(
    existing_lines: Iterable[str],
    new_records: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    merged = _parse_existing_lines(existing_lines)
    index_by_instance_id: dict[str, int] = {}

    for index, record in enumerate(merged):
        instance_id = _record_instance_id(record, f"existing record at index {index}")
        if instance_id in index_by_instance_id:
            previous = index_by_instance_id[instance_id]
            merged[previous] = record
            merged[index] = None  # type: ignore[assignment]
        else:
            index_by_instance_id[instance_id] = index

    merged = [record for record in merged if record is not None]
    index_by_instance_id = {
        _record_instance_id(record, f"existing record at index {index}"): index
        for index, record in enumerate(merged)
    }

    seen_new: set[str] = set()
    for record in new_records:
        candidate = dict(record)
        instance_id = _record_instance_id(candidate, "new record")
        if instance_id in seen_new:
            raise JsonlError(f"duplicate new record for instance_id '{instance_id}'")
        seen_new.add(instance_id)

        existing_index = index_by_instance_id.get(instance_id)
        if existing_index is None:
            index_by_instance_id[instance_id] = len(merged)
            merged.append(candidate)
        else:
            merged[existing_index] = candidate

    return merged


def dumps_jsonl(records: Iterable[Mapping[str, Any]]) -> str:
    lines = [json.dumps(record, sort_keys=True, separators=(",", ":")) for record in records]
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _parse_existing_lines(lines: Iterable[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise JsonlError(f"invalid JSON on existing JSONL line {line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise JsonlError(f"existing JSONL line {line_number} must be a JSON object")
        records.append(record)
    return records


def _record_instance_id(record: Mapping[str, Any], context: str) -> str:
    instance_id = record.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id:
        raise JsonlError(f"{context} must contain a non-empty string instance_id")
    return instance_id


def _coerce_positive_int(value: int | str, name: str) -> int:
    if isinstance(value, bool):
        raise JsonlError(f"{name} must be a positive integer")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdecimal() and int(value) > 0:
        return int(value)
    raise JsonlError(f"{name} must be a positive integer")
