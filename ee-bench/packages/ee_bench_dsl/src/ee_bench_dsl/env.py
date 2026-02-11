"""Environment variable helper."""

from __future__ import annotations

import os


_SENTINEL = object()


def env(name: str, default: object = _SENTINEL) -> str:
    """Read an environment variable.

    Args:
        name: Environment variable name.
        default: Optional default value. If not provided and the variable
            is missing, a ``ValueError`` is raised.

    Returns:
        The environment variable value, or *default* if provided.

    Raises:
        ValueError: If *name* is not set and no *default* was given.
    """
    value = os.environ.get(name)
    if value is not None:
        return value
    if default is not _SENTINEL:
        return default  # type: ignore[return-value]
    raise ValueError(f"Required environment variable '{name}' is not set")
