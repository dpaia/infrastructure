"""Tests for shared EE-bench result parsers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ee_bench_parser_junit as junit
import ee_bench_parser_trx as trx


def test_trx_aggregate_preserves_match_metadata():
    methods = [
        {
            "name": "Namespace.Outer+Inner.Case(value: 1)",
            "canonical_name": "Namespace.Outer.Inner.Case(value: 1)",
            "match_keys": [
                "Namespace.Outer+Inner.Case(value: 1)",
                "Namespace.Outer.Inner.Case(value: 1)",
            ],
            "duration_seconds": 0.1,
            "status": "passed",
        }
    ]

    result = trx.aggregate(methods)

    assert result["passed_tests"][0]["canonical_name"] == (
        "Namespace.Outer.Inner.Case(value: 1)"
    )
    assert "Namespace.Outer.Inner.Case(value: 1)" in result["passed_tests"][0]["match_keys"]


def test_junit_aggregate_preserves_match_metadata():
    methods = [
        {
            "name": "pkg.FooTest.case",
            "canonical_name": "pkg.FooTest.case",
            "match_keys": ["pkg.FooTest.case"],
            "duration_seconds": 0.1,
            "status": "failed",
            "type": "assertion",
        }
    ]

    result = junit.aggregate(methods)

    assert result["failed_tests"][0]["canonical_name"] == "pkg.FooTest.case"
    assert result["summary"]["failed"] == 1
