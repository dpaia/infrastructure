#!/usr/bin/env python3
"""Emit EE-bench JSON v2.0 evaluation output (7 criteria).

Language-independent emitter. Reads criteria status from environment
variables (set by run.sh) and parser JSON files from /tmp.
Prints the result JSON to stdout.

Environment variables consumed:
    COMPILE_STATUS, COMPILE_DURATION, PATCH_STATUS, PATCH_DURATION,
    TEST_DURATION, BASELINE_DURATION, OVERALL_DURATION, TIMESTAMP,
    HAS_TEST_PATCH

Temp files consumed:
    /tmp/_compile_output.txt, /tmp/_patch_output.txt, /tmp/_expected.json,
    /tmp/baseline_parser.json, /tmp/eval_parser.json,
    /tmp/eval_stdout.log, /tmp/eval_stderr.log
"""
import json
import os
import re

MAX_OUTPUT = 8192


def read_file(path, limit=MAX_OUTPUT):
    try:
        with open(path) as f:
            return f.read(limit)
    except FileNotFoundError:
        return ""


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _prefix(name):
    """Strip parameterized suffix: 'Foo.Bar(x: 1)' -> 'Foo.Bar'."""
    return re.sub(r"\(.*\)$", "", name)


def _normalize_name(name):
    """Normalize test name: strip module prefix (before ':'), replace '#' with '.'.

    Supports formats like 'module:com.example.FooTest#testMethod' →
    'com.example.FooTest.testMethod'.
    """
    if ":" in name:
        name = name.split(":", 1)[1]
    return name.replace("#", ".")


def _test_in(name, name_set):
    """Match by exact name, prefix (parameterized tests), or class-level prefix.

    Supports class-level expected names like 'com.example.FooTest' matching
    method-level actual names like 'com.example.FooTest.shouldDoSomething'.
    Also supports 'module:class#method' format via normalization.
    """
    name = _normalize_name(name)
    if name in name_set:
        return True
    pname = _prefix(name)
    if pname in {_prefix(n) for n in name_set}:
        return True
    # Class-level match: expected 'a.b.FooTest' matches 'a.b.FooTest.method'
    class_prefix = name + "."
    return any(n.startswith(class_prefix) for n in name_set)


def _evaluate_criterion(expected, eval_passed, baseline_passed, baseline_failed,
                        has_test_patch, should_fail_baseline, empty_status):
    """Evaluate a fail_to_pass or pass_to_pass criterion.

    Args:
        expected: list of expected test names
        eval_passed: set of test names that passed in eval run
        baseline_passed: set of test names that passed in baseline run
        baseline_failed: set of test names that failed in baseline run
        has_test_patch: whether a test patch was applied
        should_fail_baseline: True for fail_to_pass (tests must fail in baseline)
        empty_status: "fail" or "skipped" — status when expected list is empty
    Returns:
        (status, detail_string) tuple
    """
    if not expected:
        label = "no expected tests defined" if empty_status == "fail" else "no expected tests"
        return empty_status, label

    # Check eval: all expected tests must pass after submission
    eval_ok = all(_test_in(t, eval_passed) for t in expected)

    # Check baseline consistency (only if test patch exists)
    baseline_ok = True
    baseline_bad = []
    if has_test_patch:
        for t in expected:
            # Skip tests not present in baseline (likely added by test_patch)
            nt = _normalize_name(t)
            if nt not in baseline_passed and nt not in baseline_failed:
                pfx = _prefix(nt)
                baseline_names = {_prefix(n) for n in baseline_passed | baseline_failed}
                if pfx not in baseline_names:
                    continue
            if should_fail_baseline:
                # fail_to_pass: test should fail in baseline
                if _test_in(t, baseline_passed):
                    baseline_bad.append(t)
            else:
                # pass_to_pass: test should pass in baseline
                if not _test_in(t, baseline_passed):
                    baseline_bad.append(t)
        baseline_ok = not baseline_bad

    status = "pass" if (eval_ok and baseline_ok) else "fail"

    detail_parts = []
    if not eval_ok:
        missing = [t for t in expected if not _test_in(t, eval_passed)]
        detail_parts.append("eval missing: " + ", ".join(missing[:10]))
    if not baseline_ok:
        label = "baseline unexpected pass" if should_fail_baseline else "baseline missing"
        detail_parts.append(label + ": " + ", ".join(baseline_bad[:10]))

    if should_fail_baseline:
        success_msg = "all fail_to_pass tests fixed"
    else:
        success_msg = "all pass_to_pass tests still passing"

    return status, "; ".join(detail_parts) if detail_parts else success_msg


def _matches_any_expected(actual_name, expected_names):
    """True if actual_name matches any expected name via _test_in semantics.

    Reuses the same matching semantics used for fail_to_pass/pass_to_pass:
    exact, parameterized-prefix, class-level prefix, and module-prefix.
    """
    return any(_test_in(exp, {actual_name}) for exp in expected_names)


def _evaluate_fail_to_fail(expected, eval_passed, baseline_passed,
                           empty_status="skipped"):
    """Evaluate fail_to_fail criterion.

    Each listed test must NOT appear in baseline_passed NOR in eval_passed
    (i.e. it should have failed or been absent in both runs).

    Returns:
        (status, detail_string) tuple
    """
    if not expected:
        return empty_status, "no expected fail_to_fail tests"

    eval_unexpected = [t for t in expected if _test_in(t, eval_passed)]
    baseline_unexpected = [t for t in expected if _test_in(t, baseline_passed)]

    detail_parts = []
    if eval_unexpected:
        detail_parts.append("eval unexpected pass: " + ", ".join(eval_unexpected[:10]))
    if baseline_unexpected:
        detail_parts.append(
            "baseline unexpected pass: " + ", ".join(baseline_unexpected[:10])
        )

    if detail_parts:
        return "fail", "; ".join(detail_parts)
    return "pass", "all fail_to_fail tests still failing"


def main():
    compile_status = os.environ.get("COMPILE_STATUS", "fail")
    compile_duration = int(os.environ.get("COMPILE_DURATION", "0"))
    patch_status = os.environ.get("PATCH_STATUS", "skipped")
    patch_duration = int(os.environ.get("PATCH_DURATION", "0"))
    test_duration = int(os.environ.get("TEST_DURATION", "0"))
    baseline_duration = int(os.environ.get("BASELINE_DURATION", "0"))
    overall_duration = int(os.environ.get("OVERALL_DURATION", "0"))
    timestamp = os.environ.get("TIMESTAMP", "")
    has_test_patch = os.environ.get("HAS_TEST_PATCH", "false") == "true"

    compile_output = read_file("/tmp/_compile_output.txt")
    patch_output = read_file("/tmp/_patch_output.txt")

    baseline_data = load_json("/tmp/baseline_parser.json")
    eval_data = load_json("/tmp/eval_parser.json")

    baseline_passed = {
        t["name"] for t in baseline_data.get("passed_tests", []) if isinstance(t, dict)
    }
    baseline_failed = {
        t["name"] for t in baseline_data.get("failed_tests", []) if isinstance(t, dict)
    }
    eval_passed = {
        t["name"] for t in eval_data.get("passed_tests", []) if isinstance(t, dict)
    }
    eval_failed_set = {
        t["name"] for t in eval_data.get("failed_tests", []) if isinstance(t, dict)
    }

    expected = load_json("/tmp/_expected.json")
    expected_f2p = expected.get("fail_to_pass", [])
    expected_p2p = expected.get("pass_to_pass", [])
    expected_f2f = expected.get("fail_to_fail", [])
    fail_to_fail_strict = expected.get("fail_to_fail_strict", True)

    # Expand wildcards: ["*"] means "all discovered tests"
    all_eval_tests = sorted(
        {t["name"] for t in eval_data.get("passed_tests", []) if isinstance(t, dict)}
        | {t["name"] for t in eval_data.get("failed_tests", []) if isinstance(t, dict)}
    )
    if expected_f2p == ["*"]:
        expected_f2p = all_eval_tests
    if expected_p2p == ["*"]:
        # Exclude fail_to_fail names from the wildcard — "expected to still fail"
        # and "expected to still pass" are contradictory on the same test.
        if expected_f2f:
            expected_p2p = [
                n for n in all_eval_tests
                if not _matches_any_expected(n, expected_f2f)
            ]
        else:
            expected_p2p = all_eval_tests

    can_run = compile_status == "pass" and patch_status in ("pass", "skipped")

    eval_summary = eval_data.get("summary", {
        "total": 0, "passed": 0, "failed": 0,
        "errors": 0, "skipped": 0, "duration_seconds": 0.0,
    })

    eval_summary_failed = eval_summary.get("failed", 0)
    if not fail_to_fail_strict and expected_f2f:
        excluded = {
            n for n in eval_failed_set if _matches_any_expected(n, expected_f2f)
        }
        eval_summary_failed = max(0, eval_summary_failed - len(excluded))

    # --- Criterion: baseline_tests ---
    baseline_status = "pass" if compile_status == "pass" else "skipped"

    # --- Criterion: tests (eval run) ---
    tests_status = "skipped" if not can_run else (
        "fail" if eval_summary_failed > 0 else "pass"
    )

    # --- Criterion: fail_to_pass ---
    if not expected_f2p:
        f2p_status, f2p_detail = "skipped", "no expected fail_to_pass tests"
    elif not can_run:
        f2p_status, f2p_detail = "skipped", "skipped due to compilation or patch failure"
    else:
        f2p_status, f2p_detail = _evaluate_criterion(
            expected_f2p, eval_passed, baseline_passed, baseline_failed,
            has_test_patch, should_fail_baseline=True, empty_status="fail",
        )

    # --- Criterion: pass_to_pass ---
    if not expected_p2p:
        p2p_status, p2p_detail = "skipped", "no expected pass_to_pass tests"
    elif not can_run:
        p2p_status, p2p_detail = "skipped", "skipped due to compilation or patch failure"
    else:
        p2p_status, p2p_detail = _evaluate_criterion(
            expected_p2p, eval_passed, baseline_passed, baseline_failed,
            has_test_patch, should_fail_baseline=False, empty_status="skipped",
        )

    # --- Criterion: fail_to_fail ---
    if not expected_f2f:
        f2f_status, f2f_detail = "skipped", "no expected fail_to_fail tests"
    elif not can_run:
        f2f_status, f2f_detail = "skipped", "skipped due to compilation or patch failure"
    else:
        f2f_status, f2f_detail = _evaluate_fail_to_fail(
            expected_f2f, eval_passed, baseline_passed, empty_status="skipped",
        )

    # --- Overall status ---
    # tests_status is intentionally omitted - raw test failures are surfaced via fail_to_pass / fail_to_fail.
    has_failure = any(
        s == "fail" for s in [compile_status, patch_status, f2p_status, p2p_status, f2f_status]
    )
    overall_status = "failure" if has_failure else "success"

    eval_test_output = read_file("/tmp/eval_stdout.log") + read_file("/tmp/eval_stderr.log")

    result = {
        "schema_version": "2.0",
        "status": overall_status,
        "timestamp": timestamp,
        "duration_seconds": overall_duration,
        "criteria": [
            {
                "criterion": "compilation",
                "status": compile_status,
                "duration_seconds": compile_duration,
                "output": compile_output,
            },
            {
                "criterion": "baseline_tests",
                "status": baseline_status,
                "duration_seconds": baseline_duration,
                "passed_tests": sorted(baseline_passed),
                "failed_tests": baseline_data.get("failed_tests", []),
            },
            {
                "criterion": "patch_applied",
                "status": patch_status,
                "duration_seconds": patch_duration,
                "output": patch_output,
            },
            {
                "criterion": "tests",
                "status": tests_status,
                "duration_seconds": test_duration,
                "output": eval_test_output,
                "summary": eval_summary,
                "passed_tests": eval_data.get("passed_tests", []),
                "failed_tests": eval_data.get("failed_tests", []),
                "skipped_tests": eval_data.get("skipped_tests", []),
                "methods": eval_data.get("methods", []),
            },
            {
                "criterion": "fail_to_pass",
                "status": f2p_status,
                "expected": expected_f2p,
                "detail": f2p_detail,
            },
            {
                "criterion": "pass_to_pass",
                "status": p2p_status,
                "expected": expected_p2p,
                "detail": p2p_detail,
            },
            {
                "criterion": "fail_to_fail",
                "status": f2f_status,
                "expected": expected_f2f,
                "detail": f2f_detail,
                "strict": fail_to_fail_strict,
            },
        ],
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
