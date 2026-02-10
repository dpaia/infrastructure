"""ee_bench_patch_splitter - Patch splitter provider for ee_bench_generator.

This package provides an enrichment provider that separates a unified diff
into source-only and test-only patches based on file path patterns.
"""

from ee_bench_patch_splitter.provider import PatchSplitterProvider

__version__ = "0.1.0"

__all__ = [
    "PatchSplitterProvider",
]
