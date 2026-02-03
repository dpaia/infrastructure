"""ee_bench_dpaia - DPAIA generator for ee_bench_generator.

This package provides generators that produce dataset records in the
DPAIA (Data Patcher AI Agent) format for JVM-based projects.
"""

from ee_bench_dpaia.generator import DpaiaJvmGenerator

__version__ = "0.1.0"

__all__ = [
    "DpaiaJvmGenerator",
]
