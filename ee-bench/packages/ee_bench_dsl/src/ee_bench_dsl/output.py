"""Lightweight JSON/JSONL output writer (no PyYAML dependency)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterator


def write_output(
    records: Iterator[dict[str, Any]],
    path: str | Path | None = None,
    fmt: str = "jsonl",
) -> int:
    """Write records to a file or stdout.

    Args:
        records: Iterator of record dicts.
        path: Output file path.  ``None`` means stdout.
        fmt: ``"jsonl"`` (default) or ``"json"``.

    Returns:
        Number of records written.
    """
    if path is None:
        return _write_stream(records, sys.stdout, fmt)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        return _write_stream(records, f, fmt)


def _write_stream(records: Iterator[dict[str, Any]], stream, fmt: str) -> int:
    if fmt == "jsonl":
        count = 0
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")
            count += 1
        return count
    elif fmt == "json":
        items = list(records)
        json.dump(items, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        return len(items)
    else:
        raise ValueError(f"Unsupported output format: {fmt!r}")
