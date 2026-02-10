"""Tests for import sync state management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ee_bench_importer.sync_state import (
    ImportState,
    ItemState,
    check_sync_status,
    get_state_summary,
    load_state,
    remove_item_state,
    save_state,
    update_item_state,
)


@pytest.fixture
def state_file(tmp_path):
    return tmp_path / "test-state.json"


@pytest.fixture
def sample_state():
    state = ImportState(dataset="swe-bench-pro")
    state.items["item-1"] = ItemState(
        checksum="abc123",
        pr_number=42,
        pr_url="https://github.com/dpaia/django/pull/42",
        fork_repo="dpaia/django",
        status="created",
    )
    state.items["item-2"] = ItemState(
        checksum="def456",
        pr_number=43,
        pr_url="https://github.com/dpaia/flask/pull/43",
        fork_repo="dpaia/flask",
        status="error",
    )
    return state


class TestLoadState:
    def test_load_nonexistent_file(self, state_file):
        state = load_state(state_file)
        assert state.dataset == ""
        assert state.items == {}

    def test_load_existing_file(self, state_file, sample_state):
        save_state(sample_state, state_file)
        loaded = load_state(state_file)
        assert loaded.dataset == "swe-bench-pro"
        assert "item-1" in loaded.items
        assert loaded.items["item-1"].pr_number == 42

    def test_load_corrupted_file(self, state_file):
        state_file.write_text("not valid json{{{")
        state = load_state(state_file)
        assert state.items == {}  # Falls back to empty state


class TestSaveState:
    def test_save_creates_directories(self, tmp_path):
        deep_path = tmp_path / "a" / "b" / "state.json"
        state = ImportState(dataset="test")
        save_state(state, deep_path)
        assert deep_path.exists()

    def test_save_atomic(self, state_file, sample_state):
        save_state(sample_state, state_file)
        # Temp file should be cleaned up
        assert not state_file.with_suffix(".tmp").exists()

    def test_save_roundtrip(self, state_file, sample_state):
        save_state(sample_state, state_file)
        loaded = load_state(state_file)
        assert loaded.dataset == sample_state.dataset
        assert len(loaded.items) == len(sample_state.items)
        assert loaded.items["item-1"].checksum == "abc123"
        assert loaded.items["item-2"].status == "error"


class TestCheckSyncStatus:
    def test_new_item(self):
        state = ImportState()
        assert check_sync_status(state, "new-item", "checksum1") == "create"

    def test_unchanged_item(self, sample_state):
        assert check_sync_status(sample_state, "item-1", "abc123") == "skip"

    def test_changed_item(self, sample_state):
        assert check_sync_status(sample_state, "item-1", "different-checksum") == "update"

    def test_errored_item_with_same_checksum(self, sample_state):
        # Items with error status should be retried
        assert check_sync_status(sample_state, "item-2", "def456") == "update"


class TestUpdateItemState:
    def test_add_new_item(self):
        state = ImportState()
        update_item_state(
            state, "test-1", checksum="abc", pr_number=1,
            pr_url="https://example.com/1", fork_repo="org/repo",
        )
        assert "test-1" in state.items
        assert state.items["test-1"].pr_number == 1

    def test_update_existing_item(self, sample_state):
        update_item_state(
            sample_state, "item-1", checksum="new-checksum",
            pr_number=42, status="updated",
        )
        assert sample_state.items["item-1"].checksum == "new-checksum"
        assert sample_state.items["item-1"].status == "updated"


class TestRemoveItemState:
    def test_remove_existing(self, sample_state):
        assert remove_item_state(sample_state, "item-1") is True
        assert "item-1" not in sample_state.items

    def test_remove_nonexistent(self, sample_state):
        assert remove_item_state(sample_state, "nonexistent") is False


class TestGetStateSummary:
    def test_summary(self, sample_state):
        summary = get_state_summary(sample_state)
        assert summary == {"created": 1, "error": 1}

    def test_empty_summary(self):
        state = ImportState()
        summary = get_state_summary(state)
        assert summary == {}
