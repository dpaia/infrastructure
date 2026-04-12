#!/usr/bin/env python3
"""EE-bench methodgen evaluator — 4 criteria.

Applies a submission patch, validates syntax via tree-sitter,
resolves the target method from the AST, runs scoped pattern checks,
and optionally invokes a custom validation script.

Prints v2.0 JSON result to stdout.

Usage:
    python3 ee_bench_methodgen.py \
        --project-root /repo \
        --patch /ee-bench/submission/patch.diff \
        --target '{"language":"java","target":{"file":"src/...","method_signature":"m(String)","validations":[]}}' \
        [--custom-validator /ee-bench/eval/scripts/validate_method.py] \
        [--timestamp 2026-04-09T12:00:00Z] \
        [--duration-seconds 3]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile


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


def _find_method_nodes(root_node, language: str, target_sig: str):
    """Walk the AST and return all nodes whose signature matches *target_sig*."""
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
            # Strip the outer braces
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

def apply_patch(project_root: str, patch_path: str) -> dict:
    """Criterion 1: patch_applied."""
    if not os.path.isfile(patch_path):
        return {"criterion": "patch_applied", "status": "skipped", "detail": "patch.diff missing"}

    result = subprocess.run(
        ["git", "apply", patch_path],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return {"criterion": "patch_applied", "status": "pass"}
    return {
        "criterion": "patch_applied",
        "status": "fail",
        "detail": (result.stdout + result.stderr).strip()[:2048],
    }


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

    # Check for parse errors
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


def evaluate_patterns(
    config: dict,
    method_text: str | None,
    body_text: str | None,
    file_text: str | None,
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
        scope = rule["scope"]
        pattern = rule["pattern"]
        text = scope_map.get(scope, "")

        match = re.search(pattern, text, re.DOTALL)

        if rule_type == "contains":
            passed = match is not None
        elif rule_type == "not_contains":
            passed = match is None
        else:
            passed = False

        if not passed:
            all_pass = False

        checks.append({
            "pattern": pattern,
            "scope": scope,
            "type": rule_type,
            "pass": passed,
        })

    return {
        "criterion": "pattern_checks",
        "status": "pass" if all_pass else "fail",
        "checks": checks,
    }


def run_custom_validation(
    project_root: str,
    target_file: str,
    validator_path: str,
    method_text: str | None,
    body_text: str | None,
    file_text: str | None,
) -> dict:
    """Criterion 4: custom_validation."""
    if not os.path.isfile(validator_path):
        return {"criterion": "custom_validation", "status": "skipped",
                "detail": "validate_method.py not provided"}

    if method_text is None:
        return {"criterion": "custom_validation", "status": "skipped",
                "detail": "skipped — syntax invalid or patch not applied"}

    target_file_abs = os.path.join(project_root, target_file)

    # Write method_text and body_text to temp files
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as mt:
        mt.write(method_text or "")
        mt_path = mt.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as bt:
        bt.write(body_text or "")
        bt_path = bt.name

    try:
        result = subprocess.run(
            [
                "python3", validator_path,
                "--method-text", mt_path,
                "--body-text", bt_path,
                "--file", target_file_abs,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"criterion": "custom_validation", "status": "fail",
                "detail": "custom validator timed out (30s)"}
    finally:
        os.unlink(mt_path)
        os.unlink(bt_path)

    if result.returncode != 0:
        return {
            "criterion": "custom_validation",
            "status": "fail",
            "detail": f"script exit code {result.returncode}: {(result.stdout + result.stderr).strip()[:2048]}",
        }

    try:
        checks = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "criterion": "custom_validation",
            "status": "fail",
            "detail": f"invalid JSON output: {result.stdout.strip()[:1024]}",
        }

    all_pass = all(c.get("pass", False) for c in checks)
    return {
        "criterion": "custom_validation",
        "status": "pass" if all_pass else "fail",
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="EE-bench methodgen evaluator")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--patch", required=True)
    parser.add_argument("--target", required=True,
                        help="JSON string with language, target.file, target.method_signature, target.validations")
    parser.add_argument("--custom-validator", default="")
    parser.add_argument("--timestamp", default="")
    parser.add_argument("--duration-seconds", type=int, default=0)
    args = parser.parse_args()

    config = json.loads(args.target)

    criteria = []

    # --- Criterion 1: patch_applied ---
    patch_result = apply_patch(args.project_root, args.patch)
    criteria.append(patch_result)
    patch_ok = patch_result["status"] == "pass"

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
        pattern_result = evaluate_patterns(config, method_text, body_text, file_text)
    else:
        pattern_result = {"criterion": "pattern_checks", "status": "skipped",
                          "detail": "skipped — patch not applied or syntax invalid"}
    criteria.append(pattern_result)

    # --- Criterion 4: custom_validation ---
    if patch_ok and syntax_ok and args.custom_validator:
        custom_result = run_custom_validation(
            args.project_root, config["target"]["file"], args.custom_validator,
            method_text, body_text, file_text,
        )
    elif not (patch_ok and syntax_ok):
        custom_result = {"criterion": "custom_validation", "status": "skipped",
                         "detail": "skipped — patch not applied or syntax invalid"}
    else:
        custom_result = {"criterion": "custom_validation", "status": "skipped",
                         "detail": "validate_method.py not provided"}
    criteria.append(custom_result)

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
