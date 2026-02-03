"""List command - shows available plugins."""

from __future__ import annotations

import click

from ee_bench_generator import list_generators, list_providers

from ee_bench_cli.cli import Context, pass_context


@click.command("list")
@click.option(
    "--providers",
    "-p",
    is_flag=True,
    help="Show only providers.",
)
@click.option(
    "--generators",
    "-g",
    is_flag=True,
    help="Show only generators.",
)
@pass_context
def list_plugins(ctx: Context, providers: bool, generators: bool) -> None:
    """List available provider and generator plugins.

    Shows the name and capabilities of each installed plugin.
    """
    # If neither flag is set, show both
    show_providers = providers or not (providers or generators)
    show_generators = generators or not (providers or generators)

    if show_providers:
        _list_providers(ctx)

    if show_providers and show_generators:
        click.echo()  # Separator

    if show_generators:
        _list_generators(ctx)


def _list_providers(ctx: Context) -> None:
    """List all available providers."""
    providers = list_providers()

    if not providers:
        click.echo("No providers installed.")
        return

    click.echo("Providers:")
    click.echo("-" * 40)

    for name, metadata in providers:
        click.echo(f"  {name}")
        click.echo(f"    Sources: {', '.join(metadata.sources)}")

        if ctx.verbose:
            click.echo("    Provided fields:")
            for field in metadata.provided_fields:
                req = "" if field.required else " (optional)"
                click.echo(f"      - {field.name} ({field.source}){req}")


def _list_generators(ctx: Context) -> None:
    """List all available generators."""
    generators = list_generators()

    if not generators:
        click.echo("No generators installed.")
        return

    click.echo("Generators:")
    click.echo("-" * 40)

    for name, metadata in generators:
        click.echo(f"  {name}")
        click.echo(f"    Required fields: {len(metadata.required_fields)}")
        click.echo(f"    Optional fields: {len(metadata.optional_fields)}")

        if ctx.verbose:
            if metadata.required_fields:
                click.echo("    Required:")
                for field in metadata.required_fields:
                    click.echo(f"      - {field.name} ({field.source})")
            if metadata.optional_fields:
                click.echo("    Optional:")
                for field in metadata.optional_fields:
                    click.echo(f"      - {field.name} ({field.source})")
