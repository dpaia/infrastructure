import pytest

from eval_readiness.jsonl import JsonlError, dumps_jsonl, merge_by_instance_id, normalize_datapoint


def test_normalize_datapoint_injects_identity_without_mutating_input() -> None:
    source = {
        "instance_id": "old",
        "repo": "old/repo",
        "pr_number": 1,
        "prompt": "keep me",
    }

    normalized = normalize_datapoint(source, "dpaia/Kavita", "36", "kavita-36")

    assert source["instance_id"] == "old"
    assert normalized == {
        "instance_id": "kavita-36",
        "repo": "dpaia/Kavita",
        "pr_number": 36,
        "source_repo": "dpaia/Kavita",
        "source_pr_number": 36,
        "prompt": "keep me",
    }


def test_merge_replaces_existing_record_by_instance_id() -> None:
    existing = [
        '{"instance_id":"a","value":"old"}\n',
        '{"instance_id":"b","value":"keep"}\n',
    ]
    new = [{"instance_id": "a", "value": "new"}]

    assert merge_by_instance_id(existing, new) == [
        {"instance_id": "a", "value": "new"},
        {"instance_id": "b", "value": "keep"},
    ]


def test_merge_appends_new_records_and_preserves_unrelated_order() -> None:
    existing = [
        '{"instance_id":"a","value":1}\n',
        '{"instance_id":"b","value":2}\n',
    ]
    new = [
        {"instance_id": "c", "value": 3},
        {"instance_id": "d", "value": 4},
    ]

    assert merge_by_instance_id(existing, new) == [
        {"instance_id": "a", "value": 1},
        {"instance_id": "b", "value": 2},
        {"instance_id": "c", "value": 3},
        {"instance_id": "d", "value": 4},
    ]


def test_merge_collapses_existing_duplicates_without_duplicate_output() -> None:
    existing = [
        '{"instance_id":"a","value":"stale"}\n',
        '{"instance_id":"b","value":"keep"}\n',
        '{"instance_id":"a","value":"latest"}\n',
    ]

    assert merge_by_instance_id(existing, []) == [
        {"instance_id": "a", "value": "latest"},
        {"instance_id": "b", "value": "keep"},
    ]


def test_merge_rejects_duplicate_new_records() -> None:
    with pytest.raises(JsonlError, match="duplicate new record"):
        merge_by_instance_id([], [{"instance_id": "a"}, {"instance_id": "a"}])


def test_dumps_jsonl_uses_sorted_keys_and_trailing_newline() -> None:
    output = dumps_jsonl([{"z": 1, "instance_id": "b"}, {"repo": "x", "instance_id": "a"}])

    assert output == '{"instance_id":"b","z":1}\n{"instance_id":"a","repo":"x"}\n'


def test_dumps_jsonl_empty_records_returns_empty_string() -> None:
    assert dumps_jsonl([]) == ""


def test_merge_rejects_invalid_existing_json() -> None:
    with pytest.raises(JsonlError, match="invalid JSON"):
        merge_by_instance_id(["not-json\n"], [])


def test_normalize_rejects_invalid_pr_number() -> None:
    with pytest.raises(JsonlError, match="source_pr_number"):
        normalize_datapoint({}, "dpaia/Kavita", "nope", "kavita-36")
