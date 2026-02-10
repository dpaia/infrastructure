"""Generic Jinja2 template rendering for all generators.

Provides a single entry point — ``render_template()`` — with built-in
filters (``first_sentence``, ``truncate_title``) that any generator can use.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from jinja2 import ChainableUndefined, Environment

MAX_GH_TITLE_LEN = 256


def _first_sentence(text: str) -> str:
    """Extract first sentence: up to first period-followed-by-space, or first newline."""
    if not text:
        return ""
    # Match up to first ". " or ".\n" or standalone "\n"
    match = re.match(r"^(.*?\.)\s", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # No period found — take first line
    return text.split("\n", 1)[0].strip()


def _truncate_title(text: str) -> str:
    """Truncate to GitHub's max PR title length."""
    text = text.strip()
    if len(text) <= MAX_GH_TITLE_LEN:
        return text
    return text[: MAX_GH_TITLE_LEN - 3].rstrip() + "..."


def render_template(
    template_str: str,
    variables: dict[str, Any],
    extra_filters: dict[str, Callable] | None = None,
    extra_globals: dict[str, Any] | None = None,
) -> str:
    """Render a Jinja2 template string with variables.

    All generators can use this as the single entry point for template rendering.

    Args:
        template_str: Jinja2 template string.
        variables: Dict of variable names to values (passed to ``render()``).
        extra_filters: Additional Jinja2 filters to register.
        extra_globals: Additional Jinja2 globals to register.

    Returns:
        Rendered string.
    """
    env = Environment(keep_trailing_newline=True, undefined=ChainableUndefined)
    # Built-in filters available to all generators
    env.filters["first_sentence"] = _first_sentence
    env.filters["truncate_title"] = _truncate_title
    if extra_filters:
        env.filters.update(extra_filters)
    if extra_globals:
        env.globals.update(extra_globals)
    tmpl = env.from_string(template_str)
    return tmpl.render(**variables)
