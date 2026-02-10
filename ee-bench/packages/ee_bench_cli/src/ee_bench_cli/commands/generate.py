"""Generate command - runs the dataset generation pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from ee_bench_generator import DatasetEngine, MultiGeneratorRunner, Selection
from ee_bench_generator.errors import IncompatiblePluginsError, PluginNotFoundError

from ee_bench_cli.cli import Context, pass_context
from ee_bench_cli.output import write_records
from ee_bench_cli.plugin_loader import build_generators_from_config, build_provider_from_config


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
@click.option(
    "--defer-validation",
    is_flag=True,
    default=False,
    help="Defer provider/generator compatibility check until after prepare(). "
    "Useful for providers that discover fields dynamically.",
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
    defer_validation: bool,
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
    config = ctx.config or {}

    # Resolve defer_validation: CLI flag or config validation.defer
    validation_config = config.get("validation", {})
    if isinstance(validation_config, dict):
        defer_validation = defer_validation or validation_config.get("defer", False)

    # Parse CLI key=value options
    cli_provider_options = _parse_key_value_options(provider_option)
    cli_generator_options = _parse_key_value_options(generator_option)

    # Detect plural config format
    use_multi_provider = "providers" in config
    use_multi_generator = "generators" in config

    # --- Build provider ---
    try:
        if use_multi_provider:
            # Plural providers: use plugin_loader
            prov, provider_options = build_provider_from_config(config)
            # CLI provider options are not supported with plural providers
            if cli_provider_options:
                click.echo(
                    "Warning: --provider-option is ignored when using 'providers:' config.",
                    err=True,
                )
        else:
            # Singular provider: support CLI override
            prov, provider_options = _build_single_provider_with_cli(
                config, provider, cli_provider_options
            )
    except PluginNotFoundError as e:
        raise click.ClickException(
            f"Provider '{e.name}' not found. Use 'ee-dataset list' to see available providers."
        )
    except ValueError as e:
        raise click.ClickException(str(e))

    # --- Selection ---
    selection_data: dict[str, Any] | None = None
    if selection:
        try:
            selection_data = parse_selection(selection)
        except Exception as e:
            raise click.ClickException(f"Failed to parse selection: {e}")
    elif "selection" in config:
        selection_data = config["selection"]
    else:
        raise click.ClickException(
            "Selection is required. Use -s/--selection or set 'selection' in config file."
        )

    try:
        sel = Selection(
            resource=selection_data.get("resource", ""),
            filters=selection_data.get("filters", {}),
            limit=selection_data.get("limit"),
        )
    except Exception as e:
        raise click.ClickException(f"Invalid selection: {e}")

    # --- Build generator(s) and run ---
    try:
        if use_multi_generator:
            _run_multi_generator(
                ctx, config, prov, sel, provider_options,
                cli_generator_options, defer_validation,
            )
        else:
            _run_single_generator(
                ctx, config, prov, sel, provider_options,
                generator, cli_generator_options, out, output_format,
                defer_validation,
            )
    except PluginNotFoundError as e:
        raise click.ClickException(
            f"Generator '{e.name}' not found. Use 'ee-dataset list' to see available generators."
        )
    except IncompatiblePluginsError as e:
        raise click.ClickException(f"Plugin incompatibility: {e}")
    except Exception as e:
        raise click.ClickException(f"Generation failed: {e}")


def _run_single_generator(
    ctx: Context,
    config: dict[str, Any],
    prov,
    sel,
    provider_options: dict[str, Any],
    generator_cli: str | None,
    cli_generator_options: dict[str, str],
    out: Path | None,
    output_format: str | None,
    defer_validation: bool = False,
) -> None:
    """Run a single generator (original behavior)."""
    from ee_bench_generator import load_generator

    # Resolve generator name
    generator_config = config.get("generator")
    if isinstance(generator_config, dict):
        config_generator_name = generator_config.get("name")
        config_generator_options = generator_config.get("options", {})
    else:
        config_generator_name = generator_config
        config_generator_options = {}

    generator_name = generator_cli or config_generator_name
    if not generator_name:
        raise click.ClickException(
            "Generator is required. Use -g/--generator or set 'generator' in config file."
        )

    # Output settings
    output_config = config.get("output", {})
    out = out or Path(output_config.get("path", "out.jsonl"))
    output_format = output_format or output_config.get("format", "jsonl")

    # Merge generator options: nested config < flat config < CLI
    generator_options = {
        **config_generator_options,
        **config.get("generator_options", {}),
        **cli_generator_options,
    }

    gen = load_generator(generator_name)

    engine = DatasetEngine(prov, gen, defer_validation=defer_validation)

    if ctx.verbose and not ctx.quiet:
        click.echo(f"Provider: {prov.metadata.name}", err=True)
        click.echo(f"Generator: {generator_name}", err=True)
        click.echo(f"Output: {out} ({output_format})", err=True)

    records = engine.run(
        sel,
        provider_options=provider_options,
        generator_options=generator_options,
    )

    count = write_records(records, out, output_format)

    if not ctx.quiet:
        click.echo(f"Generated {count} record(s) to {out}")


def _run_multi_generator(
    ctx: Context,
    config: dict[str, Any],
    prov,
    sel,
    provider_options: dict[str, Any],
    cli_generator_options: dict[str, str],
    defer_validation: bool = False,
) -> None:
    """Run multiple generators using MultiGeneratorRunner."""
    specs = build_generators_from_config(config)

    if ctx.verbose and not ctx.quiet:
        click.echo(f"Provider: {prov.metadata.name}", err=True)
        click.echo(f"Generators: {', '.join(s.name for s in specs)}", err=True)

    runner = MultiGeneratorRunner(prov, specs, defer_validation=defer_validation)
    iterators = runner.run(
        sel,
        provider_options=provider_options,
    )

    total_count = 0
    for spec in specs:
        records = iterators[spec.name]
        out_cfg = spec.output_config
        out_path = Path(out_cfg.get("path", f"out-{spec.name}.jsonl"))
        out_format = out_cfg.get("format", "jsonl")

        count = write_records(records, out_path, out_format)
        total_count += count

        if not ctx.quiet:
            click.echo(f"  [{spec.name}] Generated {count} record(s) to {out_path}")

    if not ctx.quiet:
        click.echo(f"Total: {total_count} record(s) across {len(specs)} generator(s)")


def _build_single_provider_with_cli(
    config: dict[str, Any],
    provider_cli: str | None,
    cli_provider_options: dict[str, str],
) -> tuple:
    """Build a single provider, allowing CLI overrides."""
    from ee_bench_generator import load_provider

    provider_config = config.get("provider")
    if isinstance(provider_config, dict):
        config_provider_name = provider_config.get("name")
        config_provider_options = provider_config.get("options", {})
    else:
        config_provider_name = provider_config
        config_provider_options = {}

    provider_name = provider_cli or config_provider_name
    if not provider_name:
        raise click.ClickException(
            "Provider is required. Use -p/--provider or set 'provider' in config file."
        )

    # Merge options: nested config < flat config < CLI
    provider_options = {
        **config_provider_options,
        **config.get("provider_options", {}),
        **cli_provider_options,
    }

    prov = load_provider(provider_name)
    return prov, provider_options


def _parse_key_value_options(options: tuple[str, ...]) -> dict[str, str]:
    """Parse key=value options into a dictionary."""
    result = {}
    for opt in options:
        if "=" not in opt:
            raise click.BadParameter(f"Invalid option format: '{opt}' (expected key=value)")
        key, value = opt.split("=", 1)
        result[key] = value
    return result
