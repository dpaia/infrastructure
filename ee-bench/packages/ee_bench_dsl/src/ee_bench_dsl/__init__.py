"""ee_bench_dsl — Python DSL for building ee-bench pipelines.

Example::

    from ee_bench_dsl import Pipeline, from_items, each, env

    Pipeline() \\
        .provider(from_items([{"id": 1}, {"id": 2}])) \\
        .generator(each(lambda item, ctx: {"doubled": item["id"] * 2})) \\
        .select("items") \\
        .output("results.jsonl") \\
        .run()
"""

from ee_bench_dsl.env import env
from ee_bench_dsl.generators import FunctionGenerator, each
from ee_bench_dsl.output import write_output
from ee_bench_dsl.pipeline import Pipeline
from ee_bench_dsl.providers import FunctionProvider, from_items
from ee_bench_dsl.runner import run_script

__version__ = "0.1.0"

__all__ = [
    "Pipeline",
    "env",
    "each",
    "from_items",
    "write_output",
    "run_script",
    "FunctionProvider",
    "FunctionGenerator",
]
