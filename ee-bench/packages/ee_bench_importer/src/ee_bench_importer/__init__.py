"""ee_bench_importer - GitHub PR importer generator for ee_bench_generator.

This package provides a generator that imports dataset items as GitHub PRs,
creating forks, branches, and pull requests with structured metadata.
"""

from ee_bench_importer.generator import GitHubPRImporterGenerator

__version__ = "0.1.0"

__all__ = [
    "GitHubPRImporterGenerator",
]
