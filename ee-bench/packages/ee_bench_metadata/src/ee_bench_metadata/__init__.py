"""ee_bench_metadata - Metadata enrichment provider for ee_bench_generator.

This package provides enrichment providers that extract metadata fields
from ``<!--METADATA-->`` blocks and markdown ``##`` sections in text
(e.g. PR bodies).
"""

from ee_bench_metadata.provider import MetadataProvider
from ee_bench_metadata.section_provider import SectionProvider

__version__ = "0.1.0"

__all__ = [
    "MetadataProvider",
    "SectionProvider",
]
