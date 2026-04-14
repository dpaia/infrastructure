"""Python function signature normalizer for ee-bench methodgen evaluator.

Converts full Python function signatures to the canonical tree-sitter form: name(param1,param2)
"""
import re


def normalize(sig: str) -> str:
    """Normalize a Python function signature to canonical form: ``name(param1,param2)``.

    Accepts both ``func(a,b)`` and ``def func(self, a: int, b: str) -> bool:`` forms.
    Strips ``def``, type annotations, defaults, return type, ``self``/``cls``.
    """
    sig = sig.strip().rstrip(":")

    # Already in canonical form
    if re.match(r"^\w+\([^)]*\)$", sig) and not sig.startswith("def "):
        return sig

    # Strip decorators if present
    sig = re.sub(r"@\w+(\([^)]*\))?\s*", "", sig)

    # Strip 'async def' or 'def'
    sig = re.sub(r"^(async\s+)?def\s+", "", sig)

    # Strip return annotation
    sig = re.sub(r"\)\s*->.*", ")", sig)

    paren_idx = sig.index("(")
    name = sig[:paren_idx].strip()
    params_raw = sig[paren_idx + 1:].rstrip(")").strip()

    param_names: list[str] = []
    if params_raw:
        for param in params_raw.split(","):
            param = param.strip()
            # Strip default values
            param = param.split("=")[0].strip()
            # Strip type annotations
            param = param.split(":")[0].strip()
            # Strip * and **
            param = param.lstrip("*")
            if param and param not in ("self", "cls"):
                param_names.append(param)

    return f"{name}({','.join(param_names)})"
