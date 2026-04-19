"""provenance — identifier + data-extraction chain.

Guards against: NCT/PMID/DOI drift (off-by-one digit), citation swaps,
negated-counts silent corruption ("Not Randomized 1,807" extracted as
N=1,807 when real N=5,050). Every identifier + extracted numeric value
has a recorded source and verifier.
"""
from mission_critical.provenance.store import (
    ProvenanceEntry,
    ProvenanceStore,
)

__all__ = ["ProvenanceEntry", "ProvenanceStore"]
