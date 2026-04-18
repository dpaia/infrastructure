"""Tests for ee_bench_eval helpers.

Run: python3 -m pytest guides/templates/shared/scripts/test_ee_bench_eval.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ee_bench_eval as evalmod


def test_matches_any_expected_exact():
    assert evalmod._matches_any_expected("pkg.FooTest.testA", ["pkg.FooTest.testA"])


def test_matches_any_expected_class_level():
    assert evalmod._matches_any_expected("pkg.FooTest.testA", ["pkg.FooTest"])


def test_matches_any_expected_no_match():
    assert not evalmod._matches_any_expected("pkg.FooTest.testA", ["pkg.Other.testB"])


def test_fail_to_fail_empty_list_skipped():
    status, detail = evalmod._evaluate_fail_to_fail(
        expected=[], eval_passed=set(), baseline_passed=set(),
    )
    assert status == "skipped"
    assert "no expected" in detail


def test_fail_to_fail_all_still_failing_passes():
    status, detail = evalmod._evaluate_fail_to_fail(
        expected=["pkg.FlakyTest.one", "pkg.FlakyTest.two"],
        eval_passed={"other.test"},
        baseline_passed={"other.test"},
    )
    assert status == "pass"
    assert "still failing" in detail


def test_fail_to_fail_eval_unexpected_pass_fails():
    status, detail = evalmod._evaluate_fail_to_fail(
        expected=["pkg.FlakyTest.one"],
        eval_passed={"pkg.FlakyTest.one"},
        baseline_passed=set(),
    )
    assert status == "fail"
    assert "eval unexpected pass" in detail


def test_fail_to_fail_baseline_unexpected_pass_fails():
    status, detail = evalmod._evaluate_fail_to_fail(
        expected=["pkg.FlakyTest.one"],
        eval_passed=set(),
        baseline_passed={"pkg.FlakyTest.one"},
    )
    assert status == "fail"
    assert "baseline unexpected pass" in detail
