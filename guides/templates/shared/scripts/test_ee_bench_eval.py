"""Tests for ee_bench_eval helpers.

Run: python3 -m pytest guides/templates/shared/scripts/test_ee_bench_eval.py -v
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ee_bench_eval as evalmod


def test_matches_any_expected_exact():
    assert evalmod._matches_any_expected("pkg.FooTest.testA", ["pkg.FooTest.testA"])


def test_matches_any_expected_by_canonical_name():
    actual = {
        "name": "raw display name",
        "canonical_name": "pkg.FooTest.testA",
    }
    expected = {
        "name": "different raw display name",
        "canonical_name": "pkg.FooTest.testA",
    }
    assert evalmod._matches_any_expected(actual, [expected])


def test_matches_any_expected_by_match_key():
    actual = {
        "name": "raw display name",
        "match_keys": ["pkg.FooTest.testA", "legacy:FooTest.testA"],
    }
    expected = {
        "name": "different raw display name",
        "match_keys": ["pkg.FooTest.testA"],
    }
    assert evalmod._matches_any_expected(actual, [expected])


def test_matches_any_expected_class_level():
    assert evalmod._matches_any_expected("pkg.FooTest.testA", ["pkg.FooTest"])


def test_matches_any_expected_nested_class_separator():
    assert evalmod._matches_any_expected(
        "pkg.Outer.Inner.testA",
        ["pkg.Outer+Inner.testA"],
    )


def test_matches_any_expected_nested_class_separator_on_both_sides():
    assert evalmod._matches_any_expected(
        "pkg.Outer+Inner.testA",
        ["pkg.Outer+Inner.testA"],
    )


def test_matches_json_unicode_escape_with_actual_unicode():
    assert evalmod._matches_any_expected(
        r'pkg.Outer+Inner.testA(value: "\ud83c\udf0d")',
        ['pkg.Outer+Inner.testA(value: "🌍")'],
    )


def test_colon_in_parameter_name_is_not_treated_as_module_prefix():
    actual = 'pkg.Outer+Inner.testA(markup: "::", expected: ":🌍:")'
    assert evalmod._matches_any_expected(actual, [actual])


def test_parameterized_cases_do_not_match_by_method_prefix():
    assert not evalmod._matches_any_expected(
        'pkg.Outer+Inner.testA(value: "other")',
        ['pkg.Outer+Inner.testA(value: "target")'],
    )


def test_unparameterized_expected_can_match_parameterized_actual():
    assert evalmod._matches_any_expected(
        'pkg.Outer+Inner.testA(value: "target")',
        ["pkg.Outer+Inner.testA"],
    )


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


def test_tests_status_fails_on_non_zero_exit_code():
    status, exit_failed = evalmod._evaluate_tests_status(
        can_run=True,
        eval_summary_failed=0,
        eval_test_exit_code=1,
        expected_f2f=[],
        fail_to_fail_strict=True,
    )
    assert status == "fail"
    assert exit_failed


def test_tests_status_allows_non_zero_exit_for_non_strict_fail_to_fail():
    status, exit_failed = evalmod._evaluate_tests_status(
        can_run=True,
        eval_summary_failed=0,
        eval_test_exit_code=1,
        expected_f2f=["pkg.ExpectedFailure.one"],
        fail_to_fail_strict=False,
    )
    assert status == "pass"
    assert not exit_failed


def test_overall_status_fails_when_tests_criterion_fails(monkeypatch, capsys):
    monkeypatch.setenv("COMPILE_STATUS", "pass")
    monkeypatch.setenv("PATCH_STATUS", "skipped")
    monkeypatch.setenv("EVAL_TEST_EXIT_CODE", "0")

    def fake_load_json(path):
        if path == "/tmp/_expected.json":
            return {"pass_to_pass": ["pkg.StableTest.case"]}
        if path == "/tmp/baseline_parser.json":
            return {
                "passed_tests": [{"name": "pkg.StableTest.case"}],
                "failed_tests": [],
                "summary": {
                    "total": 1,
                    "passed": 1,
                    "failed": 0,
                    "errors": 0,
                    "skipped": 0,
                    "duration_seconds": 0,
                },
            }
        if path == "/tmp/eval_parser.json":
            return {
                "passed_tests": [{"name": "pkg.StableTest.case"}],
                "failed_tests": [{"name": "pkg.UnexpectedError.case"}],
                "summary": {
                    "total": 2,
                    "passed": 1,
                    "failed": 0,
                    "errors": 1,
                    "skipped": 0,
                    "duration_seconds": 0,
                },
            }
        return {}

    monkeypatch.setattr(evalmod, "load_json", fake_load_json)
    monkeypatch.setattr(evalmod, "read_file", lambda path, limit=evalmod.MAX_OUTPUT: "")

    evalmod.main()
    result = json.loads(capsys.readouterr().out)

    assert result["status"] == "failure"
    criteria = {item["criterion"]: item for item in result["criteria"]}
    assert criteria["tests"]["status"] == "fail"
    assert criteria["pass_to_pass"]["status"] == "pass"
