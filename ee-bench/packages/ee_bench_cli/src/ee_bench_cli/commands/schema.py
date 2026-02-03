"""Schema command - export JSON schema for generator output."""

from __future__ import annotations

import json

import click

from ee_bench_generator import load_generator
from ee_bench_generator.errors import PluginNotFoundError

from ee_bench_cli.cli import Context, pass_context


@click.command()
@click.option(
    "--generator",
    "-g",
    required=True,
    help="Generator plugin name.",
)
@click.option(
    "--out",
    "-o",
    type=click.Path(),
    help="Output file path (stdout if not specified).",
)
@pass_context
def schema(ctx: Context, generator: str, out: str | None) -> None:
    """Export the JSON schema for a generator's output format.

    Examples:

        ee-dataset schema --generator dpaia_jvm
        ee-dataset schema -g dpaia_jvm -o schema.json
    """
    try:
        gen = load_generator(generator)
    except PluginNotFoundError:
        raise click.ClickException(
            f"Generator '{generator}' not found. "
            f"Use 'ee-dataset list' to see available generators."
        )

    schema_data = gen.output_schema()
    schema_json = json.dumps(schema_data, indent=2)

    if out:
        with open(out, "w") as f:
            f.write(schema_json)
        if not ctx.quiet:
            click.echo(f"Schema written to {out}")
    else:
        click.echo(schema_json)
