"""Check command - validate provider/generator compatibility."""

from __future__ import annotations

import click

from ee_bench_generator import load_generator, load_provider, validate_compatibility
from ee_bench_generator.errors import PluginNotFoundError

from ee_bench_cli.cli import Context, pass_context


@click.command()
@click.option(
    "--provider",
    "-p",
    required=True,
    help="Provider plugin name.",
)
@click.option(
    "--generator",
    "-g",
    required=True,
    help="Generator plugin name.",
)
@pass_context
def check(ctx: Context, provider: str, generator: str) -> None:
    """Check if a provider and generator are compatible.

    Validates that the provider can supply all fields required by the generator.

    Examples:

        ee-dataset check --provider github_pull_requests --generator dpaia_jvm
        ee-dataset check -p github_issues -g dpaia_jvm
    """
    # Load plugins
    try:
        prov = load_provider(provider)
    except PluginNotFoundError:
        raise click.ClickException(
            f"Provider '{provider}' not found. "
            f"Use 'ee-dataset list' to see available providers."
        )

    try:
        gen = load_generator(generator)
    except PluginNotFoundError:
        raise click.ClickException(
            f"Generator '{generator}' not found. "
            f"Use 'ee-dataset list' to see available generators."
        )

    # Check compatibility
    result = validate_compatibility(prov.metadata, gen.metadata)

    if result.compatible:
        click.echo(
            click.style("✓ Compatible", fg="green")
            + f": {provider} can satisfy {generator}"
        )

        if result.missing_optional:
            click.echo()
            click.echo("Note: The following optional fields are not available:")
            for field in result.missing_optional:
                click.echo(f"  - {field.name} ({field.source})")
    else:
        click.echo(
            click.style("✗ Incompatible", fg="red")
            + f": {provider} cannot satisfy {generator}"
        )
        click.echo()
        click.echo("Missing required fields:")
        for field in result.missing_required:
            click.echo(f"  - {field.name} ({field.source})")

        if result.missing_optional:
            click.echo()
            click.echo("Missing optional fields:")
            for field in result.missing_optional:
                click.echo(f"  - {field.name} ({field.source})")

        raise SystemExit(1)
