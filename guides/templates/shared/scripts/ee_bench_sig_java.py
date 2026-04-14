"""Java method signature normalizer for ee-bench methodgen evaluator.

Converts full Java method signatures to the canonical tree-sitter form: name(Type1,Type2)
"""
import re

_JAVA_MODIFIERS = {
    "public", "private", "protected", "static", "final",
    "abstract", "synchronized", "native", "default", "strictfp",
}


def normalize(sig: str) -> str:
    """Normalize a Java method signature to canonical form: ``name(Type1,Type2)``.

    Accepts both short (``parse(String,Locale)``) and full
    (``public PetType parse(String text, Locale locale) throws ParseException``) forms.
    Strips annotations, modifiers, return type, parameter names, generics, and throws clause.
    """
    sig = sig.strip().rstrip(";")

    # Already in canonical form: name(Type1,Type2)
    if re.match(r"^\w+\([^)]*\)$", sig) and " " not in sig.split("(")[0]:
        # Still strip generics from param types
        name, params_str = sig.split("(", 1)
        params_str = params_str.rstrip(")")
        if not params_str:
            return f"{name}()"
        params = [re.sub(r"<[^>]*>", "", p.strip()) for p in params_str.split(",")]
        return f"{name}({','.join(params)})"

    # Strip annotations (e.g. @Override, @Transactional(...))
    sig = re.sub(r"@\w+(\([^)]*\))?\s*", "", sig)

    # Strip throws clause
    sig = re.sub(r"\)\s*throws\s+.*", ")", sig)

    # Split into tokens before the parenthesis
    paren_idx = sig.index("(")
    prefix = sig[:paren_idx].strip()
    params_raw = sig[paren_idx + 1:].rstrip(")").strip()

    # prefix is something like: "public static List findAll" or "findAll"
    tokens = prefix.split()
    # Remove modifiers
    while tokens and tokens[0] in _JAVA_MODIFIERS:
        tokens.pop(0)
    # Remove generic type params on the method itself: <T> or <T, R>
    while tokens and tokens[0].startswith("<"):
        tokens.pop(0)
    # Now tokens = [return_type, method_name] or just [method_name]
    name = tokens[-1] if tokens else prefix

    # Parse parameter types: "String text, Locale locale" -> ["String", "Locale"]
    param_types: list[str] = []
    if params_raw:
        for param in params_raw.split(","):
            parts = param.strip().split()
            if parts:
                # Strip annotations from params: @Param("x") String x -> String
                type_parts = [p for p in parts if not p.startswith("@") and not p.startswith('"')]
                if len(type_parts) >= 2:
                    raw_type = type_parts[-2]
                elif len(type_parts) == 1:
                    raw_type = type_parts[0]
                else:
                    raw_type = parts[0]
                # Strip generics
                raw_type = re.sub(r"<[^>]*>", "", raw_type)
                param_types.append(raw_type)

    return f"{name}({','.join(param_types)})"
