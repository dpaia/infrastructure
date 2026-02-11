"""run-script command — execute a Python DSL pipeline script."""

from __future__ import annotations

from pathlib import Path

import click

from ee_bench_cli.cli import Context, pass_context


@click.command("run-script")
@click.argument("script", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--set",
    "-S",
    "set_options",
    multiple=True,
    metavar="KEY=VALUE",
    help="Set environment variable for the script (can be repeated).",
)
@pass_context
def run_script_cmd(
    ctx: Context,
    script: Path,
    set_options: tuple[str, ...],
) -> None:
    """Execute a Python pipeline script.

    The script can use the ee_bench_dsl package to build and run pipelines.

    Examples:

        ee-dataset run-script scripts/my_pipeline.py

        ee-dataset run-script scripts/my_pipeline.py -S GITHUB_TOKEN=xxx
    """
    from ee_bench_dsl.runner import run_script

    variables: dict[str, str] = {}
    for opt in set_options:
        if "=" not in opt:
            raise click.BadParameter(
                f"Invalid format: '{opt}' (expected KEY=VALUE)", param_hint="'-S'"
            )
        key, value = opt.split("=", 1)
        variables[key] = value

    try:
        result = run_script(script, variables=variables or None)
    except FileNotFoundError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"Script failed: {e}")

    if result is not None and not ctx.quiet:
        click.echo(f"Script completed (result: {result})")
    elif not ctx.quiet:
        click.echo("Script completed.")
