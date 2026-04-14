#!/usr/bin/env python3
"""EE-bench methodgen evaluator — pure evaluation logic, no subprocess calls.

Validates a method implementation using tree-sitter AST parsing,
scoped regex pattern checks, and optional test result evaluation.

Patch application, compilation, and test execution are handled by run.sh.
This script only reads results and evaluates criteria.

Prints v2.0 JSON result to stdout.

Usage:
    python3 ee_bench_methodgen.py \
        --project-root /repo \
        --patch-status pass \
        --target '{"language":"java","target":{"file":"src/...","method_signature":"m(String)","validations":[]}}' \
        [--test-result-json /tmp/test_parser.json] \
        [--timestamp 2026-04-09T12:00:00Z] \
        [--duration-seconds 3]
"""
import argparse
import json
import os
import re
import sys


# ---------------------------------------------------------------------------
# Tree-sitter helpers
# ---------------------------------------------------------------------------

def _get_parser(language: str):
    """Return a tree-sitter Parser configured for *language*."""
    import tree_sitter

    if language == "java":
        import tree_sitter_java as ts_lang
    elif language == "python":
        import tree_sitter_python as ts_lang
    else:
        raise ValueError(f"Unsupported language: {language}")

    lang = ts_lang.language()

    try:
        parser = tree_sitter.Parser(lang)
    except TypeError:
        parser = tree_sitter.Parser()
        parser.language = tree_sitter.Language(lang)

    return parser


def _java_method_signature(node) -> str | None:
    """Extract a canonical method signature from a tree-sitter Java method_declaration node.

    Returns e.g. ``findCommentsByFeatureCode(String,int,int)`` or ``None``
    if the node is not a method_declaration.
    """
    if node.type != "method_declaration":
        return None

    name_node = node.child_by_field_name("name")
    params_node = node.child_by_field_name("parameters")
    if name_node is None or params_node is None:
        return None

    name = name_node.text.decode()

    param_types: list[str] = []
    for child in params_node.children:
        if child.type == "formal_parameter" or child.type == "spread_parameter":
            type_node = child.child_by_field_name("type")
            if type_node is not None:
                raw = type_node.text.decode()
                # Strip generics for matching: List<CommentDto> -> List
                simple = re.sub(r"<.*>", "", raw)
                param_types.append(simple)

    return f"{name}({','.join(param_types)})"


def _python_method_signature(node) -> str | None:
    """Extract a canonical signature from a tree-sitter Python function_definition node."""
    if node.type != "function_definition":
        return None

    name_node = node.child_by_field_name("name")
    params_node = node.child_by_field_name("parameters")
    if name_node is None:
        return None

    name = name_node.text.decode()

    param_names: list[str] = []
    if params_node is not None:
        for child in params_node.children:
            if child.type == "identifier":
                param_names.append(child.text.decode())
            elif child.type in ("typed_parameter", "default_parameter", "typed_default_parameter"):
                id_node = child.child_by_field_name("name") or next(
                    (c for c in child.children if c.type == "identifier"), None
                )
                if id_node is not None:
                    param_names.append(id_node.text.decode())

    # Exclude 'self'/'cls' for matching
    param_names = [p for p in param_names if p not in ("self", "cls")]
    return f"{name}({','.join(param_names)})"


_SIGNATURE_EXTRACTORS = {
    "java": ("method_declaration", _java_method_signature),
    "python": ("function_definition", _python_method_signature),
}


# ---------------------------------------------------------------------------
# Signature normalizer — auto-discovers ee_bench_sig_<language>.py modules
# ---------------------------------------------------------------------------

def _load_normalizer(language: str):
    """Try to import ee_bench_sig_<language> from the same directory."""
    import importlib
    try:
        mod = importlib.import_module(f"ee_bench_sig_{language}")
        return mod.normalize
    except (ImportError, AttributeError):
        return None


def normalize_signature(sig: str, language: str) -> str:
    """Normalize a method signature to canonical tree-sitter form for the given language.

    Loads the normalizer from ``ee_bench_sig_<language>.py`` if present.
    Falls back to returning the signature as-is.
    """
    normalizer = _load_normalizer(language)
    if normalizer:
        return normalizer(sig)
    return sig


def _find_method_nodes(root_node, language: str, target_sig: str):
    """Walk the AST and return all nodes whose signature matches *target_sig*."""
    target_sig = normalize_signature(target_sig, language)
    node_type, extractor = _SIGNATURE_EXTRACTORS[language]
    matches = []

    def _walk(node):
        if node.type == node_type:
            sig = extractor(node)
            if sig == target_sig:
                matches.append(node)
        for child in node.children:
            _walk(child)

    _walk(root_node)
    return matches


def _extract_body_text(node, source_bytes: bytes, language: str) -> str:
    """Extract the body text from a method/function node."""
    if language == "java":
        body = node.child_by_field_name("body")
        if body is not None:
            inner = source_bytes[body.start_byte + 1 : body.end_byte - 1]
            return inner.decode().strip()
    elif language == "python":
        body = node.child_by_field_name("body")
        if body is not None:
            return source_bytes[body.start_byte : body.end_byte].decode()
    return ""


# ---------------------------------------------------------------------------
# Criterion helpers
# ---------------------------------------------------------------------------

def validate_syntax_and_resolve(
    project_root: str, config: dict
) -> tuple[dict, str | None, str | None, str | None]:
    """Criterion 2: syntax_valid.

    Returns (criterion_dict, method_text, body_text, file_text).
    On failure method_text/body_text/file_text are None.
    """
    language = config.get("language", "java")
    target = config["target"]
    target_file = os.path.join(project_root, target["file"])
    method_sig = target["method_signature"]

    if not os.path.isfile(target_file):
        return (
            {"criterion": "syntax_valid", "status": "fail",
             "detail": f"target file not found: {target['file']}"},
            None, None, None,
        )

    with open(target_file, "rb") as f:
        source_bytes = f.read()

    file_text = source_bytes.decode(errors="replace")

    try:
        parser = _get_parser(language)
    except Exception as e:
        return (
            {"criterion": "syntax_valid", "status": "fail",
             "detail": f"tree-sitter setup failed: {e}"},
            None, None, None,
        )

    tree = parser.parse(source_bytes)

    if tree.root_node.has_error:
        return (
            {"criterion": "syntax_valid", "status": "fail",
             "language": language, "file": target["file"],
             "detail": "parse errors in target file"},
            None, None, None,
        )

    matches = _find_method_nodes(tree.root_node, language, method_sig)

    if len(matches) == 0:
        return (
            {"criterion": "syntax_valid", "status": "fail",
             "language": language, "file": target["file"],
             "method_signature": method_sig,
             "detail": "target method not found"},
            None, None, None,
        )

    if len(matches) > 1:
        return (
            {"criterion": "syntax_valid", "status": "fail",
             "language": language, "file": target["file"],
             "method_signature": method_sig,
             "detail": f"multiple matches ({len(matches)}) for target method"},
            None, None, None,
        )

    node = matches[0]
    method_text = source_bytes[node.start_byte:node.end_byte].decode(errors="replace")
    body_text = _extract_body_text(node, source_bytes, language)

    return (
        {"criterion": "syntax_valid", "status": "pass",
         "language": language, "file": target["file"],
         "method_signature": method_sig},
        method_text, body_text, file_text,
    )


def _evaluate_test_check(rule: dict, test_result_json: str) -> dict:
    """Evaluate a single 'test' validation rule using JUnit parser output."""
    test_class = rule.get("test_class", "")
    check = {"type": "test", "test_class": test_class}

    if not test_result_json or not os.path.isfile(test_result_json):
        check["pass"] = False
        check["detail"] = "no test results available"
        return check

    try:
        with open(test_result_json) as f:
            test_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        check["pass"] = False
        check["detail"] = f"failed to read test results: {e}"
        return check

    passed_tests = [t for t in test_data.get("passed_tests", []) if isinstance(t, dict)]
    failed_tests = [t for t in test_data.get("failed_tests", []) if isinstance(t, dict)]
    summary = test_data.get("summary", {})

    total = summary.get("total", len(passed_tests) + len(failed_tests))
    passed = summary.get("passed", len(passed_tests))
    failed = summary.get("failed", len(failed_tests))

    if failed > 0:
        check["pass"] = False
        failed_names = [t.get("name", "?") for t in failed_tests[:5]]
        check["detail"] = f"{passed}/{total} passed, {failed} failed: {', '.join(failed_names)}"
    elif total == 0:
        check["pass"] = False
        check["detail"] = "no tests found (compilation may have failed)"
    else:
        check["pass"] = True
        check["detail"] = f"{passed}/{total} passed"

    return check


def evaluate_patterns(
    config: dict,
    method_text: str | None,
    body_text: str | None,
    file_text: str | None,
    test_result_json: str = "",
) -> dict:
    """Criterion 3: pattern_checks."""
    validations = config.get("target", {}).get("validations", [])

    if not validations:
        return {"criterion": "pattern_checks", "status": "skipped", "detail": "no rules defined"}

    if method_text is None:
        return {"criterion": "pattern_checks", "status": "skipped",
                "detail": "skipped — syntax invalid or patch not applied"}

    scope_map = {
        "method_text": method_text,
        "body_text": body_text or "",
        "file_text": file_text or "",
    }

    checks = []
    all_pass = True

    for rule in validations:
        rule_type = rule["type"]

        if rule_type == "test":
            check = _evaluate_test_check(rule, test_result_json)
        elif rule_type in ("contains", "not_contains"):
            scope = rule["scope"]
            pattern = rule["pattern"]
            text = scope_map.get(scope, "")
            match = re.search(pattern, text, re.DOTALL)

            if rule_type == "contains":
                passed = match is not None
            else:
                passed = match is None

            check = {
                "pattern": pattern,
                "scope": scope,
                "type": rule_type,
                "pass": passed,
            }
        else:
            check = {"type": rule_type, "pass": False, "detail": f"unknown rule type: {rule_type}"}

        if not check.get("pass", False):
            all_pass = False
        checks.append(check)

    return {
        "criterion": "pattern_checks",
        "status": "pass" if all_pass else "fail",
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="EE-bench methodgen evaluator")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--patch-status", required=True,
                        help="Patch application result from run.sh: pass, fail, or skipped")
    parser.add_argument("--target", required=True,
                        help="JSON string with language, target.file, target.method_signature, target.validations")
    parser.add_argument("--test-result-json", default="",
                        help="Path to JUnit parser JSON output (from ee_bench_parser_junit.py)")
    parser.add_argument("--timestamp", default="")
    parser.add_argument("--duration-seconds", type=int, default=0)
    args = parser.parse_args()

    config = json.loads(args.target)

    criteria = []

    # --- Criterion 1: patch_applied ---
    patch_status = args.patch_status
    patch_result = {"criterion": "patch_applied", "status": patch_status}
    criteria.append(patch_result)
    patch_ok = patch_status == "pass"

    # --- Criterion 2: syntax_valid ---
    if patch_ok:
        syntax_result, method_text, body_text, file_text = validate_syntax_and_resolve(
            args.project_root, config
        )
    else:
        syntax_result = {"criterion": "syntax_valid", "status": "skipped",
                         "detail": "skipped — patch_applied failed"}
        method_text = body_text = file_text = None
    criteria.append(syntax_result)
    syntax_ok = syntax_result["status"] == "pass"

    # --- Criterion 3: pattern_checks ---
    if patch_ok and syntax_ok:
        pattern_result = evaluate_patterns(
            config, method_text, body_text, file_text,
            test_result_json=args.test_result_json,
        )
    else:
        pattern_result = {"criterion": "pattern_checks", "status": "skipped",
                          "detail": "skipped — patch not applied or syntax invalid"}
    criteria.append(pattern_result)

    # --- Overall status ---
    has_failure = any(c["status"] == "fail" for c in criteria)
    overall_status = "failure" if has_failure else "success"

    result = {
        "schema_version": "2.0",
        "status": overall_status,
        "timestamp": args.timestamp,
        "duration_seconds": args.duration_seconds,
        "criteria": criteria,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
