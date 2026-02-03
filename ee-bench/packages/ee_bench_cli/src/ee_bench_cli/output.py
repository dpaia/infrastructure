"""Output serialization utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import yaml


def write_records(
    records: Iterator[dict[str, Any]],
    path: Path,
    output_format: str = "jsonl",
) -> int:
    """Write records to a file in the specified format.

    Args:
        records: Iterator of record dictionaries to write.
        path: Output file path.
        output_format: Output format - "json", "jsonl", or "yaml".

    Returns:
        Number of records written.

    Raises:
        ValueError: If output_format is not recognized.
    """
    if output_format == "jsonl":
        return _write_jsonl(records, path)
    elif output_format == "json":
        return _write_json(records, path)
    elif output_format == "yaml":
        return _write_yaml(records, path)
    else:
        raise ValueError(f"Unknown output format: {output_format}")


def _write_jsonl(records: Iterator[dict[str, Any]], path: Path) -> int:
    """Write records as JSON Lines (one JSON object per line)."""
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
            count += 1

    return count


def _write_json(records: Iterator[dict[str, Any]], path: Path) -> int:
    """Write records as a JSON array."""
    records_list = list(records)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        json.dump(records_list, f, ensure_ascii=False, indent=2)

    return len(records_list)


def _write_yaml(records: Iterator[dict[str, Any]], path: Path) -> int:
    """Write records as a YAML document."""
    records_list = list(records)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        yaml.safe_dump(records_list, f, default_flow_style=False, allow_unicode=True)

    return len(records_list)


def format_record(record: dict[str, Any], output_format: str = "json") -> str:
    """Format a single record as a string.

    Args:
        record: Record dictionary to format.
        output_format: Output format - "json" or "yaml".

    Returns:
        Formatted string representation.
    """
    if output_format == "yaml":
        return yaml.safe_dump(record, default_flow_style=False, allow_unicode=True)
    else:
        return json.dumps(record, ensure_ascii=False, indent=2)
