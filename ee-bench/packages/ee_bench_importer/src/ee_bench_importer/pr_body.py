"""Build and parse PR bodies with embedded metadata blocks.

The metadata block is a hidden HTML comment containing KEY:VALUE lines,
enabling full round-trip: import → export preserves all original data.

Format:
    <!--METADATA
    key1:value1
    key2:value2
    METADATA-->
"""

from __future__ import annotations

import re
from typing import Any

from ee_bench_generator.templates import render_template

# Regex to match the metadata block (dotall for multiline content)
METADATA_PATTERN = re.compile(
    r"<!--METADATA\n(.*?)\nMETADATA-->",
    re.DOTALL,
)


def build_pr_body(
    problem_statement: str,
    hints_text: str = "",
    metadata: dict[str, str] | None = None,
) -> str:
    """Build a PR body with problem statement, hints, and metadata block.

    Args:
        problem_statement: The problem description text.
        hints_text: Optional hints text.
        metadata: Key-value pairs to embed in the metadata block.

    Returns:
        Formatted PR body string.
    """
    parts = []

    parts.append("## Problem Statement\n")
    parts.append(problem_statement.strip() if problem_statement else "(no description)")
    parts.append("")

    if hints_text and hints_text.strip():
        parts.append("## Hints\n")
        parts.append(hints_text.strip())
        parts.append("")

    if metadata:
        parts.append(build_metadata_block(metadata))

    return "\n".join(parts)


def build_metadata_block(metadata: dict[str, str]) -> str:
    """Build the <!--METADATA ... METADATA--> block.

    Args:
        metadata: Key-value pairs to include.

    Returns:
        Formatted metadata block string.
    """
    lines = []
    for key, value in metadata.items():
        # Serialize value: convert to string, handle multi-line by escaping newlines
        str_value = str(value) if value is not None else ""
        # Replace actual newlines with \\n for single-line storage
        str_value = str_value.replace("\n", "\\n")
        lines.append(f"{key}:{str_value}")

    block_content = "\n".join(lines)
    return f"<!--METADATA\n{block_content}\nMETADATA-->"


def parse_metadata_block(body: str) -> dict[str, str]:
    """Parse the <!--METADATA ... METADATA--> block from a PR body.

    Args:
        body: PR body text.

    Returns:
        Dictionary of key-value pairs from the metadata block.
        Empty dict if no metadata block found.
    """
    match = METADATA_PATTERN.search(body)
    if not match:
        return {}

    content = match.group(1)
    result = {}

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Split on first colon only
        colon_idx = line.find(":")
        if colon_idx < 0:
            continue
        key = line[:colon_idx].strip()
        value = line[colon_idx + 1:]
        # Restore escaped newlines
        value = value.replace("\\n", "\n")
        result[key] = value

    return result


def update_metadata_in_body(body: str, new_metadata: dict[str, str]) -> str:
    """Update the metadata block in an existing PR body.

    If a metadata block exists, it is replaced. Otherwise, a new one is appended.

    Args:
        body: Existing PR body text.
        new_metadata: Updated key-value pairs.

    Returns:
        Updated PR body string.
    """
    new_block = build_metadata_block(new_metadata)

    if METADATA_PATTERN.search(body):
        return METADATA_PATTERN.sub(new_block, body)
    else:
        return body.rstrip() + "\n\n" + new_block


def resolve_metadata_fields(
    config_fields: list[str | dict[str, str]],
    item: dict[str, Any],
) -> dict[str, str]:
    """Resolve metadata fields from config + dataset item.

    Supports two formats in the config list:
    - "from:field_name" — dynamic value from dataset item
    - {"key": "value"} or "key: value" — static value

    Args:
        config_fields: List of field specs from generator options.
        item: Current dataset item dict.

    Returns:
        Resolved metadata dict.
    """
    metadata = {}

    for field_spec in config_fields:
        if isinstance(field_spec, dict):
            # Static key-value pair: {"dataset": "swe-bench-pro"}
            for key, value in field_spec.items():
                metadata[key] = str(value)
        elif isinstance(field_spec, str):
            if field_spec.startswith("from:"):
                # Dynamic field from dataset item
                field_name = field_spec[5:]
                value = item.get(field_name, "")
                metadata[field_name] = str(value) if value is not None else ""
            elif ":" in field_spec:
                # Static "key: value" or "key:value" format
                colon_idx = field_spec.find(":")
                key = field_spec[:colon_idx].strip()
                value = field_spec[colon_idx + 1:].strip()
                metadata[key] = value
            else:
                # Plain string treated as "from:field_name"
                value = item.get(field_spec, "")
                metadata[field_spec] = str(value) if value is not None else ""

    return metadata


# ---------------------------------------------------------------------------
# Jinja2 template rendering (delegates to ee_bench_generator.templates)
# ---------------------------------------------------------------------------


def _make_metadata_fn(extra_metadata: dict[str, str] | None):
    """Create a ``metadata()`` callable for use inside Jinja2 templates."""

    def metadata(**kwargs: Any) -> str:
        merged: dict[str, str] = {}
        for key, value in kwargs.items():
            merged[key] = str(value) if value is not None else ""
        if extra_metadata:
            merged.update(extra_metadata)
        return build_metadata_block(merged)

    return metadata


def render_pr_body_template(
    template_str: str,
    item: dict[str, Any],
    extra_metadata: dict[str, str] | None = None,
) -> str:
    """Render a Jinja2 PR body template with item fields as variables.

    Args:
        template_str: Jinja2 template string for the PR body.
        item: Dataset item dict — all keys become template variables.
        extra_metadata: Extra key-value pairs silently merged into the
            ``metadata()`` call (e.g. ``{"imported_at": "..."}``.

    Returns:
        Rendered PR body string.
    """
    return render_template(
        template_str,
        item,
        extra_globals={"metadata": _make_metadata_fn(extra_metadata)},
    )


def render_pr_title_template(template_str: str, item: dict[str, Any]) -> str:
    """Render a Jinja2 PR title template with item fields as variables.

    Args:
        template_str: Jinja2 template string for the PR title.
        item: Dataset item dict — all keys become template variables.

    Returns:
        Rendered PR title string.
    """
    return render_template(template_str, item)
