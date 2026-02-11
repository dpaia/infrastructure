"""ee_bench_metadata - Metadata enrichment provider for ee_bench_generator.

This package provides an enrichment provider that extracts metadata fields
from ``<!--METADATA-->`` blocks embedded in text (e.g. PR bodies).
"""

from ee_bench_metadata.provider import MetadataProvider

__version__ = "0.1.0"

__all__ = [
    "MetadataProvider",
]
