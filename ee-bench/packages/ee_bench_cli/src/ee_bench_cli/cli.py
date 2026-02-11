"""Main CLI entry point using Click."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from ee_bench_cli import __version__
from ee_bench_cli.config_parser import load_config, parse_set_options


class Context:
    """CLI context object holding configuration and options."""

    def __init__(self) -> None:
        self.config_path: Path | None = None
        self.config: dict[str, Any] = {}
        self.template_vars: dict[str, Any] | None = None
        self.verbose: int = 0
        self.quiet: bool = False


pass_context = click.make_pass_decorator(Context, ensure=True)


@click.group()
@click.version_option(version=__version__, prog_name="ee-dataset")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Path to configuration file.",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (can be repeated).",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress non-essential output.",
)
@click.option(
    "--set",
    "-S",
    "set_options",
    multiple=True,
    metavar="KEY=VALUE",
    help="Set template variable (can be repeated). Supports JSON values and nested keys (e.g., -S org=apache -S 'labels=[\"bug\"]' -S outer.inner=value).",
)
@pass_context
def cli(
    ctx: Context,
    config: Path | None,
    verbose: int,
    quiet: bool,
    set_options: tuple[str, ...],
) -> None:
    """ee-dataset: Generate datasets using pluggable providers and generators.

    Use 'ee-dataset COMMAND --help' for more information on a specific command.
    """
    ctx.verbose = verbose
    ctx.quiet = quiet

    # Parse --set options into template variables
    if set_options:
        try:
            ctx.template_vars = parse_set_options(set_options)
        except ValueError as e:
            raise click.ClickException(str(e))

    if config:
        ctx.config_path = config
        ctx.config = load_config(config, ctx.template_vars)


# Import and register commands
from ee_bench_cli.commands import check, config_cmd, generate, import_cmd, list_cmd, run_script, schema, show, validate

cli.add_command(generate.generate)
cli.add_command(list_cmd.list_plugins)
cli.add_command(show.show)
cli.add_command(schema.schema)
cli.add_command(validate.validate)
cli.add_command(check.check)
cli.add_command(config_cmd.config)
cli.add_command(import_cmd.import_group)
cli.add_command(run_script.run_script_cmd)


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
