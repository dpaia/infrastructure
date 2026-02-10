"""Import command group - import datasets into GitHub organization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from ee_bench_generator import DatasetEngine, Selection, load_generator, load_provider
from ee_bench_generator.errors import PluginNotFoundError

from ee_bench_cli.cli import Context, pass_context
from ee_bench_cli.output import write_records


@click.group("import")
def import_group() -> None:
    """Import datasets into GitHub organization as PRs.

    Commands for importing HuggingFace datasets into GitHub, creating forks,
    branches, PRs, labels, and project assignments.
    """


@import_group.command()
@pass_context
def run(ctx: Context) -> None:
    """Run the import pipeline.

    Reads provider/generator config from the YAML config file and executes
    the import, creating GitHub PRs for each dataset item.

    Example:
        ee-dataset --config specs/import-swe-bench-pro.yaml import run
    """
    _execute_import(ctx, dry_run=False)


@import_group.command("dry-run")
@pass_context
def dry_run(ctx: Context) -> None:
    """Preview import without making any changes.

    Shows what would be created/updated/skipped without writing to GitHub.

    Example:
        ee-dataset --config specs/import-swe-bench-pro.yaml import dry-run
    """
    _execute_import(ctx, dry_run=True)


@import_group.command()
@click.option(
    "--state-file",
    "-s",
    type=click.Path(exists=True, path_type=Path),
    help="Path to state file. Defaults to value in config.",
)
@pass_context
def status(ctx: Context, state_file: Path | None) -> None:
    """Show import progress summary.

    Displays counts of created, updated, skipped, and errored items.

    Example:
        ee-dataset import status --state-file .state/swe-bench-pro.json
    """
    from ee_bench_importer.sync_state import get_state_summary, load_state

    # Resolve state file path
    if not state_file:
        config = ctx.config or {}
        gen_opts = _get_generator_options(config)
        sf = gen_opts.get("state_file")
        if sf:
            state_file = Path(sf)
        else:
            raise click.ClickException(
                "State file not specified. Use --state-file or set in config."
            )

    state = load_state(state_file)
    summary = get_state_summary(state)

    click.echo(f"Dataset: {state.dataset or '(unknown)'}")
    click.echo(f"Last sync: {state.last_sync or '(never)'}")
    click.echo(f"Total items: {len(state.items)}")
    click.echo("")

    for status_name, count in sorted(summary.items()):
        click.echo(f"  {status_name}: {count}")


@import_group.command()
@click.option(
    "--instance-id",
    "-i",
    required=True,
    help="Instance ID to remove from state.",
)
@click.option(
    "--state-file",
    "-s",
    type=click.Path(path_type=Path),
    help="Path to state file. Defaults to value in config.",
)
@pass_context
def reset(ctx: Context, instance_id: str, state_file: Path | None) -> None:
    """Remove an item from the import state.

    This allows re-importing a specific item on the next run.

    Example:
        ee-dataset import reset --instance-id django__django-16255 \\
            --state-file .state/swe-bench-pro.json
    """
    from ee_bench_importer.sync_state import load_state, remove_item_state, save_state

    if not state_file:
        config = ctx.config or {}
        gen_opts = _get_generator_options(config)
        sf = gen_opts.get("state_file")
        if sf:
            state_file = Path(sf)
        else:
            raise click.ClickException(
                "State file not specified. Use --state-file or set in config."
            )

    state = load_state(state_file)
    removed = remove_item_state(state, instance_id)

    if removed:
        save_state(state, state_file)
        click.echo(f"Removed '{instance_id}' from state. It will be re-imported on next run.")
    else:
        click.echo(f"Instance '{instance_id}' not found in state.")


def _execute_import(ctx: Context, dry_run: bool) -> None:
    """Execute the import pipeline (shared by run and dry-run)."""
    config = ctx.config
    if not config:
        raise click.ClickException(
            "Config file is required. Use --config/-c to specify one."
        )

    # Resolve provider
    provider_config = config.get("provider")
    if isinstance(provider_config, dict):
        provider_name = provider_config.get("name")
        provider_options = provider_config.get("options", {})
    else:
        provider_name = provider_config
        provider_options = {}

    if not provider_name:
        raise click.ClickException("Provider name is required in config.")

    # Resolve generator
    generator_config = config.get("generator")
    if isinstance(generator_config, dict):
        generator_name = generator_config.get("name")
        generator_options = generator_config.get("options", {})
    else:
        generator_name = generator_config
        generator_options = {}

    if not generator_name:
        raise click.ClickException("Generator name is required in config.")

    # Inject dry_run into generator options
    if dry_run:
        generator_options["dry_run"] = True

    # Selection
    selection_data = config.get("selection", {})
    sel = Selection(
        resource=selection_data.get("resource", "dataset_items"),
        filters=selection_data.get("filters", {}),
        limit=selection_data.get("limit"),
    )

    # Output settings
    output_config = config.get("output", {})
    out_path = Path(output_config.get("path", "results/import-results.jsonl"))
    output_format = output_config.get("format", "jsonl")

    # Load plugins
    try:
        prov = load_provider(provider_name)
    except PluginNotFoundError:
        raise click.ClickException(
            f"Provider '{provider_name}' not found. Use 'ee-dataset list' to see available providers."
        )

    try:
        gen = load_generator(generator_name)
    except PluginNotFoundError:
        raise click.ClickException(
            f"Generator '{generator_name}' not found. Use 'ee-dataset list' to see available generators."
        )

    # Create engine with deferred validation (HuggingFace provider discovers fields at prepare time)
    engine = DatasetEngine(prov, gen, defer_validation=True)

    if ctx.verbose and not ctx.quiet:
        mode = "DRY RUN" if dry_run else "LIVE"
        click.echo(f"Mode: {mode}", err=True)
        click.echo(f"Provider: {provider_name}", err=True)
        click.echo(f"Generator: {generator_name}", err=True)
        click.echo(f"Output: {out_path} ({output_format})", err=True)

    # Run import
    try:
        records = engine.run(
            sel,
            provider_options=provider_options,
            generator_options=generator_options,
        )

        count = write_records(records, out_path, output_format)

        if not ctx.quiet:
            click.echo(f"Processed {count} item(s). Results written to {out_path}")

    except Exception as e:
        raise click.ClickException(f"Import failed: {e}")


def _get_generator_options(config: dict[str, Any]) -> dict[str, Any]:
    """Extract generator options from config."""
    generator_config = config.get("generator")
    if isinstance(generator_config, dict):
        return generator_config.get("options", {})
    return config.get("generator_options", {})
