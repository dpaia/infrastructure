"""Import state tracking for crash recovery and sync logic.

Maintains a JSON state file that records which items have been imported,
their checksums, and PR details. Used for skip/update/create decisions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ee_bench_generator.clock import now_iso8601_utc

logger = logging.getLogger(__name__)


@dataclass
class ItemState:
    """State of a single imported item."""

    checksum: str
    pr_number: int | None = None
    pr_url: str = ""
    fork_repo: str = ""
    status: str = "created"  # created, updated, skipped, error


@dataclass
class ImportState:
    """Overall import state."""

    dataset: str = ""
    last_sync: str = ""
    items: dict[str, ItemState] = field(default_factory=dict)


def load_state(state_file: str | Path) -> ImportState:
    """Load import state from a JSON file.

    Args:
        state_file: Path to the state file.

    Returns:
        ImportState object. Returns empty state if file doesn't exist.
    """
    path = Path(state_file)
    if not path.exists():
        return ImportState()

    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read state file %s: %s. Starting fresh.", path, e)
        return ImportState()

    items = {}
    for instance_id, item_data in data.get("items", {}).items():
        items[instance_id] = ItemState(
            checksum=item_data.get("checksum", ""),
            pr_number=item_data.get("pr_number"),
            pr_url=item_data.get("pr_url", ""),
            fork_repo=item_data.get("fork_repo", ""),
            status=item_data.get("status", "unknown"),
        )

    return ImportState(
        dataset=data.get("dataset", ""),
        last_sync=data.get("last_sync", ""),
        items=items,
    )


def save_state(state: ImportState, state_file: str | Path) -> None:
    """Save import state to a JSON file.

    Creates parent directories if needed. Writes atomically by writing
    to a temp file first then renaming.

    Args:
        state: ImportState to save.
        state_file: Path to write the state file.
    """
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    state.last_sync = now_iso8601_utc()

    data: dict[str, Any] = {
        "dataset": state.dataset,
        "last_sync": state.last_sync,
        "items": {},
    }
    for instance_id, item_state in state.items.items():
        data["items"][instance_id] = asdict(item_state)

    # Write to temp file then rename for atomicity
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    tmp_path.rename(path)


def check_sync_status(
    state: ImportState, instance_id: str, checksum: str
) -> str:
    """Check if an item needs to be imported, updated, or skipped.

    Args:
        state: Current import state.
        instance_id: The item's instance ID.
        checksum: Current checksum of the dataset item.

    Returns:
        One of: "skip", "update", "create"
    """
    if instance_id not in state.items:
        return "create"

    existing = state.items[instance_id]
    if existing.checksum == checksum and existing.status in ("created", "updated", "skipped"):
        return "skip"

    return "update"


def update_item_state(
    state: ImportState,
    instance_id: str,
    checksum: str,
    pr_number: int | None = None,
    pr_url: str = "",
    fork_repo: str = "",
    status: str = "created",
) -> None:
    """Update the state for a single item.

    Args:
        state: Import state to modify.
        instance_id: The item's instance ID.
        checksum: Checksum of the dataset item.
        pr_number: GitHub PR number.
        pr_url: URL to the created/updated PR.
        fork_repo: Full name of the fork repository.
        status: Import status (created/updated/skipped/error).
    """
    state.items[instance_id] = ItemState(
        checksum=checksum,
        pr_number=pr_number,
        pr_url=pr_url,
        fork_repo=fork_repo,
        status=status,
    )


def remove_item_state(state: ImportState, instance_id: str) -> bool:
    """Remove an item from the import state.

    Args:
        state: Import state to modify.
        instance_id: The item's instance ID.

    Returns:
        True if the item was found and removed, False otherwise.
    """
    if instance_id in state.items:
        del state.items[instance_id]
        return True
    return False


def get_state_summary(state: ImportState) -> dict[str, int]:
    """Get a summary of import state counts.

    Returns:
        Dict with counts per status (created, updated, skipped, error).
    """
    summary: dict[str, int] = {}
    for item in state.items.values():
        summary[item.status] = summary.get(item.status, 0) + 1
    return summary
