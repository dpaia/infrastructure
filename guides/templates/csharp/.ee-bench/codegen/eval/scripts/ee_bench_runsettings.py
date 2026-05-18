#!/usr/bin/env python3
"""Build a dotnet test .runsettings file restricting execution to the
tests referenced by fail_to_pass and pass_to_pass.

The TestCaseFilter is a disjunction of FullyQualifiedName~<TestName>
clauses, one per distinct test name (with any data-row parameters
stripped). Tests whose name contains generic/parameterized segments
(any of: , { } < > `) are skipped, because they cannot be expressed
as a simple substring filter.

Input JSON shape (from stdin or a file path passed as argv[1]):
    {"fail_to_pass": [...], "pass_to_pass": [...]}

Usage:
    python3 ee_bench_runsettings.py                    # JSON from stdin
    python3 ee_bench_runsettings.py /tmp/_expected.json
"""
import json
import sys
import xml.etree.ElementTree as ET

_CLASS_NAME_REJECT_CHARS = (",", "{", "}", "<", ">", "`")


def build_runsettings(tests: list[str]) -> str:
    test_names: set[str] = set()
    for test in tests:
        test_without_params = test.split("(", 1)[0].strip()
        if not test_without_params:
            continue
        if any(ch in test_without_params for ch in _CLASS_NAME_REJECT_CHARS):
            continue
        test_names.add(test_without_params)

    filter_expr = (
        "|".join(f"FullyQualifiedName~{t}" for t in sorted(test_names))
        if test_names
        else None
    )

    root = ET.Element("RunSettings")
    run_config = ET.SubElement(root, "RunConfiguration")
    if filter_expr:
        test_case_filter = ET.SubElement(run_config, "TestCaseFilter")
        test_case_filter.text = filter_expr

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] != "-":
        with open(sys.argv[1]) as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    tests = list(data.get("fail_to_pass", [])) + list(data.get("pass_to_pass", []))
    sys.stdout.write(build_runsettings(tests))


if __name__ == "__main__":
    main()