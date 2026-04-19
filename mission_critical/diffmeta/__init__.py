"""diffmeta — differential-engine statistical verifier.

Runs a meta-analysis in both a Python engine and R (metafor) and flags
any divergence above tolerance on pooled estimate, SE, CI bounds, or Q.
"""
from mission_critical.diffmeta.engine import (
    ComparisonResult,
    PooledResult,
    compare,
    compare_binary_or,
)

__all__ = ["ComparisonResult", "PooledResult", "compare", "compare_binary_or"]
