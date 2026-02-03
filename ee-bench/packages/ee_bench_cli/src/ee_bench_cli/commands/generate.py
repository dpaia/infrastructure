"""Generate command - runs the dataset generation pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from ee_bench_generator import DatasetEngine, Selection, load_generator, load_provider
from ee_bench_generator.errors import IncompatiblePluginsError, PluginNotFoundError

from ee_bench_cli.cli import Context, pass_context
from ee_bench_cli.output import write_records


def parse_selection(selection_str: str) -> dict[str, Any]:
    """Parse selection from JSON string or file path.

    Args:
        selection_str: JSON string or path to YAML/JSON file.

    Returns:
        Parsed selection dictionary.
    """
    # Check if it's a file path
    path = Path(selection_str)
    if path.exists():
        import yaml

        with open(path) as f:
            return yaml.safe_load(f)

    # Try parsing as JSON
    try:
        return json.loads(selection_str)
    except json.JSONDecodeError as e:
        raise click.BadParameter(f"Invalid JSON: {e}")


@click.command()
@click.option(
    "--provider",
    "-p",
    help="Provider plugin name (e.g., github_pull_requests). Can be set in config file.",
)
@click.option(
    "--generator",
    "-g",
    help="Generator plugin name (e.g., dpaia_jvm). Can be set in config file.",
)
@click.option(
    "--selection",
    "-s",
    help="Selection criteria as JSON string or path to YAML file. Can be set in config file.",
)
@click.option(
    "--out",
    "-o",
    type=click.Path(path_type=Path),
    help="Output file path. Default: out.jsonl or from config file.",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["json", "jsonl", "yaml"]),
    help="Output format. Default: jsonl or from config file.",
)
@click.option(
    "--provider-option",
    "-P",
    multiple=True,
    help="Provider option as key=value (can be repeated).",
)
@click.option(
    "--generator-option",
    "-G",
    multiple=True,
    help="Generator option as key=value (can be repeated).",
)
@pass_context
def generate(
    ctx: Context,
    provider: str | None,
    generator: str | None,
    selection: str | None,
    out: Path | None,
    output_format: str | None,
    provider_option: tuple[str, ...],
    generator_option: tuple[str, ...],
) -> None:
    """Generate a dataset using the specified provider and generator.

    All options can be provided via CLI or config file. CLI options override config.

    Examples:

        # Generate from GitHub PRs (all options via CLI)
        ee-dataset generate -p github_pull_requests -g dpaia_jvm \\
            -s '{"resource": "pull_requests", "filters": {"repo": "org/repo", "pr_numbers": [42]}}'

        # Using a config file for all settings
        ee-dataset --config config.yaml generate

        # Config file with CLI overrides
        ee-dataset --config config.yaml generate -o custom_output.jsonl
    """
    # Resolve options from config file, CLI overrides config
    config = ctx.config or {}

    # Provider (required) - supports both flat and nested format
    # Flat format: provider: github_issues
    # Nested format: provider: { name: github_issues, options: { ... } }
    provider_config = config.get("provider")
    if isinstance(provider_config, dict):
        config_provider_name = provider_config.get("name")
        config_provider_options = provider_config.get("options", {})
    else:
        config_provider_name = provider_config
        config_provider_options = {}

    provider = provider or config_provider_name
    if not provider:
        raise click.ClickException(
            "Provider is required. Use -p/--provider or set 'provider' in config file."
        )

    # Generator (required) - supports both flat and nested format
    generator_config = config.get("generator")
    if isinstance(generator_config, dict):
        config_generator_name = generator_config.get("name")
        config_generator_options = generator_config.get("options", {})
    else:
        config_generator_name = generator_config
        config_generator_options = {}

    generator = generator or config_generator_name
    if not generator:
        raise click.ClickException(
            "Generator is required. Use -g/--generator or set 'generator' in config file."
        )

    # Output settings (with defaults)
    output_config = config.get("output", {})
    out = out or Path(output_config.get("path", "out.jsonl"))
    output_format = output_format or output_config.get("format", "jsonl")

    # Parse provider and generator options from CLI
    cli_provider_options = _parse_key_value_options(provider_option)
    cli_generator_options = _parse_key_value_options(generator_option)

    # Merge options: nested config < flat config < CLI options
    # Priority: CLI options override config options
    provider_options = {
        **config_provider_options,  # From nested provider.options
        **config.get("provider_options", {}),  # From flat provider_options
        **cli_provider_options,  # From CLI --provider-option
    }
    generator_options = {
        **config_generator_options,  # From nested generator.options
        **config.get("generator_options", {}),  # From flat generator_options
        **cli_generator_options,  # From CLI --generator-option
    }

    # Selection: CLI overrides config
    selection_data: dict[str, Any] | None = None

    if selection:
        # CLI provided selection (JSON string or file path)
        try:
            selection_data = parse_selection(selection)
        except Exception as e:
            raise click.ClickException(f"Failed to parse selection: {e}")
    elif "selection" in config:
        # Config file has selection block
        selection_data = config["selection"]
    else:
        raise click.ClickException(
            "Selection is required. Use -s/--selection or set 'selection' in config file."
        )

    # Create Selection object
    try:
        sel = Selection(
            resource=selection_data.get("resource", ""),
            filters=selection_data.get("filters", {}),
            limit=selection_data.get("limit"),
        )
    except Exception as e:
        raise click.ClickException(f"Invalid selection: {e}")

    # Load plugins
    try:
        prov = load_provider(provider)
    except PluginNotFoundError:
        raise click.ClickException(
            f"Provider '{provider}' not found. Use 'ee-dataset list' to see available providers."
        )

    try:
        gen = load_generator(generator)
    except PluginNotFoundError:
        raise click.ClickException(
            f"Generator '{generator}' not found. Use 'ee-dataset list' to see available generators."
        )

    # Create engine
    try:
        engine = DatasetEngine(prov, gen)
    except IncompatiblePluginsError as e:
        raise click.ClickException(
            f"Provider '{provider}' is not compatible with generator '{generator}': {e}"
        )

    # Log if verbose
    if ctx.verbose and not ctx.quiet:
        click.echo(f"Provider: {provider}", err=True)
        click.echo(f"Generator: {generator}", err=True)
        click.echo(f"Output: {out} ({output_format})", err=True)

    # Run generation
    try:
        records = engine.run(
            sel,
            provider_options=provider_options,
            generator_options=generator_options,
        )

        count = write_records(records, out, output_format)

        if not ctx.quiet:
            click.echo(f"Generated {count} record(s) to {out}")

    except Exception as e:
        raise click.ClickException(f"Generation failed: {e}")


def _parse_key_value_options(options: tuple[str, ...]) -> dict[str, str]:
    """Parse key=value options into a dictionary."""
    result = {}
    for opt in options:
        if "=" not in opt:
            raise click.BadParameter(f"Invalid option format: '{opt}' (expected key=value)")
        key, value = opt.split("=", 1)
        result[key] = value
    return result
