"""Config command - manage configuration files."""

from __future__ import annotations

from pathlib import Path

import click
import yaml

from ee_bench_cli.cli import Context, pass_context
from ee_bench_cli.config_parser import (
    find_default_config,
    generate_sample_config,
    load_config,
    validate_config,
)


@click.group()
def config() -> None:
    """Configuration file management commands."""
    pass


@config.command("show")
@click.option(
    "--path",
    "-p",
    type=click.Path(exists=True, path_type=Path),
    help="Config file to show (uses default if not specified).",
)
@pass_context
def config_show(ctx: Context, path: Path | None) -> None:
    """Show the effective configuration.

    Displays the currently loaded configuration, including
    values from config files and environment variables.
    """
    # Determine config path
    config_path = path or ctx.config_path or find_default_config()

    if config_path:
        try:
            config_data = load_config(config_path, ctx.template_vars)
            click.echo(f"# Config file: {config_path}")
            click.echo()
            click.echo(yaml.safe_dump(config_data, default_flow_style=False))
        except Exception as e:
            raise click.ClickException(f"Failed to load config: {e}")
    else:
        click.echo("No configuration file found.")
        click.echo()
        click.echo("Searched locations:")
        click.echo("  - ./ee-dataset.yml")
        click.echo("  - ./ee-dataset.yaml")
        click.echo("  - ./datasetgen.yml")
        click.echo("  - ./datasetgen.yaml")
        click.echo("  - ~/.config/ee-dataset/config.yml")
        click.echo()
        click.echo("Use 'ee-dataset config init > config.yml' to create a sample config.")


@config.command("validate")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@pass_context
def config_validate(ctx: Context, path: Path) -> None:
    """Validate a configuration file.

    Checks the configuration file for syntax errors,
    missing required fields, and unknown keys.

    Examples:

        ee-dataset config validate config.yml
        ee-dataset config validate ee-dataset.yaml
    """
    # Try to load the config
    try:
        config_data = load_config(path, ctx.template_vars)
    except yaml.YAMLError as e:
        click.echo(click.style("✗ Invalid YAML syntax", fg="red"))
        click.echo(f"  {e}")
        raise SystemExit(1)
    except ValueError as e:
        click.echo(click.style("✗ Environment variable error", fg="red"))
        click.echo(f"  {e}")
        raise SystemExit(1)
    except Exception as e:
        click.echo(click.style("✗ Failed to load config", fg="red"))
        click.echo(f"  {e}")
        raise SystemExit(1)

    # Validate the config structure
    errors = validate_config(config_data)

    if errors:
        click.echo(click.style("✗ Configuration errors found", fg="red"))
        for error in errors:
            click.echo(f"  - {error}")
        raise SystemExit(1)
    else:
        click.echo(click.style("✓ Configuration is valid", fg="green"))


@config.command("init")
@click.option(
    "--out",
    "-o",
    type=click.Path(path_type=Path),
    help="Output file path (stdout if not specified).",
)
def config_init(out: Path | None) -> None:
    """Generate a sample configuration file.

    Creates a new configuration file with documented options
    and example values.

    Examples:

        ee-dataset config init
        ee-dataset config init > ee-dataset.yml
        ee-dataset config init -o ee-dataset.yml
    """
    sample = generate_sample_config()

    if out:
        out.write_text(sample)
        click.echo(f"Sample configuration written to {out}")
    else:
        click.echo(sample)
