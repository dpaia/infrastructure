"""Script runner — load and execute a .py pipeline script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


def run_script(
    path: str | Path,
    variables: dict[str, str] | None = None,
) -> Any:
    """Load and execute a Python pipeline script.

    Execution order:

    1. If *variables* are provided, inject them into ``os.environ``.
    2. Load the module from *path*.
    3. If the module defines a ``main()`` callable, call it.
    4. Otherwise, if the module has a ``pipeline`` attribute with a
       ``.run()`` method, call ``pipeline.run()``.
    5. Otherwise, module-level code has already executed — nothing extra.

    Args:
        path: Path to the ``.py`` file.
        variables: Optional ``KEY=VALUE`` pairs set as env vars before
            the script runs.

    Returns:
        Whatever ``main()`` or ``pipeline.run()`` returns, or ``None``.
    """
    import os

    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Script not found: {path}")

    # Inject variables into environment
    if variables:
        for key, value in variables.items():
            os.environ[key] = value

    module = _load_module(path)

    if hasattr(module, "main") and callable(module.main):
        return module.main()

    if hasattr(module, "pipeline"):
        pipeline = module.pipeline
        if hasattr(pipeline, "run") and callable(pipeline.run):
            return pipeline.run()

    return None


def _load_module(path: Path) -> ModuleType:
    """Import a .py file as a module."""
    module_name = path.stem

    # Add script's directory to sys.path so relative imports work
    script_dir = str(path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
