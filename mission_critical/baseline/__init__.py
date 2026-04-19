"""baseline — numerical continuity corpus.

Records shipped MAs' pooled estimate / CI / heterogeneity values.
Re-running the same MA diff-checks against the stored values at a
configurable tolerance. Catches silent numerical drift between paper
revisions that authors and reviewers routinely miss.
"""
from mission_critical.baseline.store import (
    BaselineRecord,
    BaselineStore,
    DiffReport,
)

__all__ = ["BaselineRecord", "BaselineStore", "DiffReport"]
