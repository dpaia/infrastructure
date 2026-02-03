"""Validate command - validate output files against schema."""

from __future__ import annotations

import json
from pathlib import Path

import click

from ee_bench_generator import load_generator
from ee_bench_generator.errors import PluginNotFoundError

from ee_bench_cli.cli import Context, pass_context


@click.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--generator",
    "-g",
    required=True,
    help="Generator plugin name (for schema).",
)
@click.option(
    "--format",
    "-f",
    "input_format",
    type=click.Choice(["json", "jsonl"]),
    default="jsonl",
    help="Input file format.",
)
@click.option(
    "--max-errors",
    type=int,
    default=10,
    help="Maximum number of errors to report.",
)
@pass_context
def validate(
    ctx: Context,
    file: Path,
    generator: str,
    input_format: str,
    max_errors: int,
) -> None:
    """Validate a dataset file against a generator's schema.

    Examples:

        ee-dataset validate output.jsonl --generator dpaia_jvm
        ee-dataset validate output.json -g dpaia_jvm -f json
    """
    # Load generator for schema
    try:
        gen = load_generator(generator)
    except PluginNotFoundError:
        raise click.ClickException(
            f"Generator '{generator}' not found. "
            f"Use 'ee-dataset list' to see available generators."
        )

    schema = gen.output_schema()

    # Try to import jsonschema for validation
    try:
        import jsonschema
    except ImportError:
        raise click.ClickException(
            "jsonschema package not installed. Install with: pip install jsonschema"
        )

    # Read records
    records = _read_records(file, input_format)

    # Validate each record
    errors = []
    valid_count = 0
    total_count = 0

    for i, record in enumerate(records, start=1):
        total_count += 1
        try:
            jsonschema.validate(record, schema)
            valid_count += 1
        except jsonschema.ValidationError as e:
            errors.append((i, str(e.message)))
            if len(errors) >= max_errors:
                break

    # Report results
    if errors:
        click.echo(f"Validation failed: {len(errors)} error(s) found", err=True)
        click.echo()
        for line_num, error in errors:
            click.echo(f"  Record {line_num}: {error}", err=True)
        if len(errors) >= max_errors:
            click.echo(f"  ... (stopped after {max_errors} errors)", err=True)
        raise SystemExit(1)
    else:
        if not ctx.quiet:
            click.echo(f"Validation passed: {valid_count}/{total_count} record(s) valid")


def _read_records(file: Path, input_format: str):
    """Read records from file."""
    with open(file) as f:
        if input_format == "jsonl":
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
        else:  # json
            data = json.load(f)
            if isinstance(data, list):
                yield from data
            else:
                yield data
