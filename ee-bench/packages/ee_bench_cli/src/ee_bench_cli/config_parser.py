"""Configuration file parsing with YAML support, Jinja2 templates, and environment variable substitution."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined, TemplateSyntaxError, UndefinedError

# Environment variable pattern: ${VAR} or ${VAR:-default}
ENV_VAR_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")

# Default config file names to search for
DEFAULT_CONFIG_NAMES = [
    "ee-dataset.yml",
    "ee-dataset.yaml",
    "datasetgen.yml",
    "datasetgen.yaml",
]

# User config directory
USER_CONFIG_DIR = Path.home() / ".config" / "ee-dataset"


def parse_set_value(value: str) -> Any:
    """Parse a value from --set option, supporting JSON.

    Tries to parse as JSON first. If that fails, returns the raw string.

    Args:
        value: The string value to parse.

    Returns:
        Parsed value (JSON object/array/string/number/bool) or raw string.

    Example:
        >>> parse_set_value("42")
        42
        >>> parse_set_value("true")
        True
        >>> parse_set_value('["a", "b"]')
        ['a', 'b']
        >>> parse_set_value("plain string")
        'plain string'
    """
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def parse_set_options(set_options: tuple[str, ...]) -> dict[str, Any]:
    """Parse --set options into a dictionary.

    Supports:
    - Simple key=value: "name=value"
    - Nested keys: "outer.inner=value"
    - JSON values: 'items=["a","b"]'

    Args:
        set_options: Tuple of "key=value" strings.

    Returns:
        Dictionary with parsed values, supporting nested keys.

    Raises:
        ValueError: If a set option is not in key=value format.

    Example:
        >>> parse_set_options(("org=apache", "limit=50", 'labels=["bug"]'))
        {'org': 'apache', 'limit': 50, 'labels': ['bug']}
        >>> parse_set_options(("outer.inner=value",))
        {'outer': {'inner': 'value'}}
    """
    result: dict[str, Any] = {}

    for option in set_options:
        if "=" not in option:
            raise ValueError(f"Invalid --set option format: '{option}'. Expected 'key=value'.")

        key, value = option.split("=", 1)
        parsed_value = parse_set_value(value)

        # Handle nested keys (e.g., "outer.inner=value")
        keys = key.split(".")
        current = result
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            elif not isinstance(current[k], dict):
                # Overwrite non-dict with dict
                current[k] = {}
            current = current[k]
        current[keys[-1]] = parsed_value

    return result


def render_template(content: str, variables: dict[str, Any] | None = None) -> str:
    """Render Jinja2 template in configuration content.

    Args:
        content: YAML content string potentially containing Jinja2 syntax.
        variables: Template variables to substitute.

    Returns:
        Rendered content string.

    Raises:
        ValueError: If template rendering fails (syntax error or undefined variable).

    Example:
        >>> render_template("repo: {{ org }}/kafka", {"org": "apache"})
        'repo: apache/kafka'
        >>> render_template("limit: {{ limit | default(100) }}", {})
        'limit: 100'
    """
    if variables is None:
        variables = {}

    # Quick check: if no Jinja2 syntax, return as-is
    if "{{" not in content and "{%" not in content:
        return content

    try:
        env = Environment(undefined=StrictUndefined)
        template = env.from_string(content)
        return template.render(**variables)
    except TemplateSyntaxError as e:
        raise ValueError(f"Jinja2 template syntax error: {e}")
    except UndefinedError as e:
        raise ValueError(f"Undefined template variable: {e}")


def substitute_env_vars(value: str) -> str:
    """Substitute environment variables in a string.

    Supports two formats:
    - ${VAR} - raises error if VAR is not set
    - ${VAR:-default} - uses 'default' if VAR is not set

    Args:
        value: String potentially containing env var references.

    Returns:
        String with env vars substituted.

    Raises:
        ValueError: If a required env var is not set.

    Example:
        >>> os.environ["TEST_VAR"] = "hello"
        >>> substitute_env_vars("${TEST_VAR} world")
        'hello world'
        >>> substitute_env_vars("${MISSING:-default}")
        'default'
    """

    def replace(match: re.Match) -> str:
        var_name = match.group(1)
        default = match.group(2)

        value = os.environ.get(var_name)
        if value is not None:
            return value
        if default is not None:
            return default
        raise ValueError(f"Environment variable '{var_name}' is not set")

    return ENV_VAR_PATTERN.sub(replace, value)


def _substitute_in_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively substitute env vars in a dictionary."""
    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = substitute_env_vars(value)
        elif isinstance(value, dict):
            result[key] = _substitute_in_dict(value)
        elif isinstance(value, list):
            result[key] = _substitute_in_list(value)
        else:
            result[key] = value
    return result


def _substitute_in_list(data: list[Any]) -> list[Any]:
    """Recursively substitute env vars in a list."""
    result = []
    for item in data:
        if isinstance(item, str):
            result.append(substitute_env_vars(item))
        elif isinstance(item, dict):
            result.append(_substitute_in_dict(item))
        elif isinstance(item, list):
            result.append(_substitute_in_list(item))
        else:
            result.append(item)
    return result


def load_config(
    path: Path, template_vars: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Load configuration from a YAML file.

    Processing order:
    1. Read raw file content
    2. Render Jinja2 templates (if template_vars provided or content has Jinja2 syntax)
    3. Parse YAML
    4. Substitute environment variables

    Args:
        path: Path to the configuration file.
        template_vars: Variables to substitute in Jinja2 templates.

    Returns:
        Parsed configuration dictionary with templates and env vars substituted.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        yaml.YAMLError: If the YAML is invalid.
        ValueError: If required env vars are missing or template rendering fails.
    """
    with open(path) as f:
        content = f.read()

    # Render Jinja2 templates if there are template variables or Jinja2 syntax
    if template_vars or "{{" in content or "{%" in content:
        content = render_template(content, template_vars)

    config = yaml.safe_load(content) or {}

    return _substitute_in_dict(config)


def find_default_config() -> Path | None:
    """Find a configuration file in default locations.

    Search order:
    1. Current directory: ee-dataset.yml, ee-dataset.yaml, datasetgen.yml, datasetgen.yaml
    2. User config: ~/.config/ee-dataset/config.yml

    Returns:
        Path to found config file, or None if not found.
    """
    # Check current directory
    cwd = Path.cwd()
    for name in DEFAULT_CONFIG_NAMES:
        config_path = cwd / name
        if config_path.exists():
            return config_path

    # Check user config directory
    user_config = USER_CONFIG_DIR / "config.yml"
    if user_config.exists():
        return user_config

    return None


def merge_configs(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two configuration dictionaries.

    Values from 'override' take precedence over 'base'.

    Args:
        base: Base configuration.
        override: Override configuration (higher priority).

    Returns:
        Merged configuration.
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value

    return result


def validate_config(config: dict[str, Any]) -> list[str]:
    """Validate a configuration dictionary.

    Args:
        config: Configuration to validate.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors = []

    # Check for unknown top-level keys
    known_keys = {
        "provider",
        "provider_options",
        "generator",
        "generator_options",
        "selection",
        "output",
        "runtime",
        "validation",
    }
    for key in config:
        if key not in known_keys:
            errors.append(f"Unknown configuration key: '{key}'")

    # Validate selection if present
    if "selection" in config:
        selection = config["selection"]
        if not isinstance(selection, dict):
            errors.append("'selection' must be a dictionary")
        elif "resource" not in selection:
            errors.append("'selection.resource' is required")

    # Validate output if present
    if "output" in config:
        output = config["output"]
        if not isinstance(output, dict):
            errors.append("'output' must be a dictionary")
        elif "format" in output:
            valid_formats = {"json", "jsonl", "yaml"}
            if output["format"] not in valid_formats:
                errors.append(
                    f"'output.format' must be one of: {', '.join(valid_formats)}"
                )

    return errors


def generate_sample_config() -> str:
    """Generate a sample configuration file.

    Returns:
        Sample configuration as a YAML string.
    """
    return """\
# ee-dataset configuration file
# See documentation for full options

# Provider configuration
# Supports two formats:
#   Flat format:
#     provider: github_pull_requests
#     provider_options:
#       token: ${GITHUB_TOKEN}
#
#   Nested format (recommended):
#     provider:
#       name: github_issues
#       options:
#         fetch_commits: true
#         parse_comments: true

# Example: Nested provider format with options
provider:
  name: github_issues
  options:
    fetch_commits: true          # Enable commit fetching from Timeline API
    parse_comments: true         # Parse test fields from comments
    detect_build_system: true    # Detect Maven/Gradle

# Generator plugin name
generator: dpaia_jvm

# Generator-specific options
generator_options:
  version: "1"
  common_labels:
    - bug
    - enhancement

# Selection criteria
selection:
  resource: issues
  filters:
    repo: owner/repository
    # issue_numbers: [42, 43]
    # state: open
    # labels: [Verified]
  # limit: 100

# Output configuration
output:
  format: json
  path: data/instance.json

# Runtime options
runtime:
  verbose: 1
  retry: 3
  # concurrency: 4
"""
