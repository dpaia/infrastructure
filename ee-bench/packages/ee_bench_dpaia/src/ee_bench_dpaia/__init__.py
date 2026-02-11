"""ee_bench_dpaia - DPAIA generators for ee_bench_generator.

This package provides generators that produce dataset records in
DPAIA (Data Patcher AI Agent) format.
"""

from ee_bench_dpaia.generator import DpaiaJvmGenerator, DpaiaSweProGenerator

__version__ = "0.1.0"

__all__ = [
    "DpaiaJvmGenerator",
    "DpaiaSweProGenerator",
]
