"""ee_bench_huggingface - HuggingFace dataset provider for ee_bench_generator.

This package provides a data provider that reads datasets from HuggingFace Hub
and exposes their columns as provider fields with dynamic discovery.
"""

from ee_bench_huggingface.provider import HuggingFaceDatasetProvider

__version__ = "0.1.0"

__all__ = [
    "HuggingFaceDatasetProvider",
]
