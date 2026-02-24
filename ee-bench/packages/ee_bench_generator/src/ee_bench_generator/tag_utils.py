"""Utilities for filtering issue/PR labels into tags."""

from __future__ import annotations

import fnmatch


def filter_tags(
    labels: list[str],
    exclude: list[str] | None = None,
    include: list[str] | None = None,
) -> list[str]:
    """Filter labels using fnmatch glob patterns.

    Semantics: exclude first, then include overrides.
    1. Start with all labels
    2. Remove any matching an exclude pattern
    3. Add back any (from original labels) matching an include pattern
    """
    if not exclude and not include:
        return list(labels)

    exclude = exclude or []
    include = include or []

    # Step 1-2: remove excluded
    filtered = [
        label for label in labels
        if not any(fnmatch.fnmatch(label, pat) for pat in exclude)
    ]

    # Step 3: add back included (from original labels, preserving order)
    if include:
        filtered_set = set(filtered)
        for label in labels:
            if label not in filtered_set and any(fnmatch.fnmatch(label, pat) for pat in include):
                filtered.append(label)
                filtered_set.add(label)

    return filtered
