"""Show command - display detailed plugin information."""

from __future__ import annotations

import click

from ee_bench_generator import load_generator, load_provider
from ee_bench_generator.errors import PluginNotFoundError

from ee_bench_cli.cli import Context, pass_context
from ee_bench_cli.output import format_record


@click.command()
@click.argument("plugin_type", type=click.Choice(["provider", "generator"]))
@click.argument("name")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["text", "json", "yaml"]),
    default="text",
    help="Output format.",
)
@pass_context
def show(ctx: Context, plugin_type: str, name: str, output_format: str) -> None:
    """Show detailed information about a plugin.

    Examples:

        ee-dataset show provider github_pull_requests
        ee-dataset show generator dpaia_jvm --format yaml
    """
    try:
        if plugin_type == "provider":
            plugin = load_provider(name)
            metadata = plugin.metadata
            _show_provider(metadata, output_format)
        else:
            plugin = load_generator(name)
            metadata = plugin.metadata
            _show_generator(metadata, output_format, plugin)
    except PluginNotFoundError:
        raise click.ClickException(
            f"{plugin_type.capitalize()} '{name}' not found. "
            f"Use 'ee-dataset list' to see available {plugin_type}s."
        )


def _show_provider(metadata, output_format: str) -> None:
    """Display provider metadata."""
    if output_format in ("json", "yaml"):
        data = {
            "name": metadata.name,
            "sources": metadata.sources,
            "provided_fields": [
                {
                    "name": f.name,
                    "source": f.source,
                    "required": f.required,
                    "description": f.description,
                }
                for f in metadata.provided_fields
            ],
        }
        click.echo(format_record(data, output_format))
    else:
        click.echo(f"Provider: {metadata.name}")
        click.echo(f"Sources: {', '.join(metadata.sources)}")
        click.echo()
        click.echo("Provided Fields:")
        for field in metadata.provided_fields:
            req = "" if field.required else " (optional)"
            desc = f" - {field.description}" if field.description else ""
            click.echo(f"  {field.name} ({field.source}){req}{desc}")


def _show_generator(metadata, output_format: str, plugin) -> None:
    """Display generator metadata."""
    if output_format in ("json", "yaml"):
        data = {
            "name": metadata.name,
            "required_fields": [
                {
                    "name": f.name,
                    "source": f.source,
                    "description": f.description,
                }
                for f in metadata.required_fields
            ],
            "optional_fields": [
                {
                    "name": f.name,
                    "source": f.source,
                    "description": f.description,
                }
                for f in metadata.optional_fields
            ],
        }
        click.echo(format_record(data, output_format))
    else:
        click.echo(f"Generator: {metadata.name}")
        click.echo()

        if metadata.required_fields:
            click.echo("Required Fields:")
            for field in metadata.required_fields:
                desc = f" - {field.description}" if field.description else ""
                click.echo(f"  {field.name} ({field.source}){desc}")

        if metadata.optional_fields:
            click.echo()
            click.echo("Optional Fields:")
            for field in metadata.optional_fields:
                desc = f" - {field.description}" if field.description else ""
                click.echo(f"  {field.name} ({field.source}){desc}")
