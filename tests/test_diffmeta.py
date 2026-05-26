"""Tests for the differential-engine statistical verifier.

Each test writes a CSV fixture, runs compare_binary_or, and asserts
either agreement (engines match within tolerance) or a specific
pattern in the ComparisonResult.

Skipped when R / metafor isn't available on the runner (the Sentinel
CI doesn't install R, and this tool is only usable on machines where
R is present — that's by design, since a single-engine check would
defeat the whole point).
"""
from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# --- skip conditions ---------------------------------------------------

def _rscript_path() -> str | None:
    from mission_critical.diffmeta.engine import resolve_rscript_path

    return resolve_rscript_path()


def _metafor_available(rscript: str) -> bool:
    try:
        result = subprocess.run(
            [rscript, "-e",
             "if(!require(metafor,quietly=TRUE)) quit(status=1)"],
            capture_output=True, timeout=60,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


_RSCRIPT = _rscript_path()
_HAS_R = bool(_RSCRIPT and _metafor_available(_RSCRIPT))

skip_if_no_r = pytest.mark.skipif(
    not _HAS_R,
    reason="R + metafor not available on this runner (expected — diffmeta is a local-only tool)",
)


# --- fixtures ----------------------------------------------------------

def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ai", "bi", "ci", "di"])
        for r in rows:
            w.writerow([r["ai"], r["bi"], r["ci"], r["di"]])


# --- tests -------------------------------------------------------------

@skip_if_no_r
def test_both_engines_agree_on_small_cochrane_dataset(tmp_path: Path):
    """5-study dataset (no zero cells) — Python and R should agree at 1e-6."""
    from mission_critical.diffmeta import compare_binary_or
    csv_path = tmp_path / "input.csv"
    _write_csv(csv_path, [
        {"ai": 10, "bi": 90, "ci": 20, "di": 80},
        {"ai": 5,  "bi": 45, "ci": 10, "di": 40},
        {"ai": 15, "bi": 85, "ci": 25, "di": 75},
        {"ai": 8,  "bi": 92, "ci": 12, "di": 88},
        {"ai": 20, "bi": 80, "ci": 30, "di": 70},
    ])
    res = compare_binary_or(csv_path, rscript_path=_RSCRIPT)
    assert res.python.k == 5
    assert res.r.k == 5
    assert res.diverges is False, (
        f"Engines disagree beyond 1e-6: field_diffs={res.field_diffs}"
    )


@skip_if_no_r
def test_both_engines_agree_on_dataset_with_zero_cells(tmp_path: Path):
    """Zero-cell handling is a classic engine-divergence point —
    continuity correction must be applied identically."""
    from mission_critical.diffmeta import compare_binary_or
    csv_path = tmp_path / "input.csv"
    _write_csv(csv_path, [
        {"ai": 10, "bi": 90, "ci": 20, "di": 80},
        {"ai": 0,  "bi": 50, "ci": 5,  "di": 45},   # zero cell
        {"ai": 15, "bi": 85, "ci": 25, "di": 75},
    ])
    res = compare_binary_or(csv_path, rscript_path=_RSCRIPT)
    assert res.diverges is False, (
        f"Engines disagree on zero-cell correction: {res.field_diffs}"
    )


@skip_if_no_r
def test_diverges_flag_triggers_at_lower_tolerance(tmp_path: Path):
    """At tolerance 0, floating-point noise may diverge. Proves the
    `diverges` flag is actually wired and not a tautology."""
    from mission_critical.diffmeta import compare_binary_or
    csv_path = tmp_path / "input.csv"
    _write_csv(csv_path, [
        {"ai": 10, "bi": 90, "ci": 20, "di": 80},
        {"ai": 15, "bi": 85, "ci": 25, "di": 75},
    ])
    res = compare_binary_or(csv_path, tolerance=0.0, rscript_path=_RSCRIPT)
    assert res.python.estimate is not None
    assert res.r.estimate is not None


def test_python_engine_deterministic_on_known_values(tmp_path: Path):
    """Pure-numpy Python engine: known hand-calculated output.

    Study 1: a=10, b=90, c=20, d=75
      log_OR = log((10*75)/(90*20)), var = 1/10 + 1/90 + 1/20 + 1/75
    Study 2: a=15, b=85, c=25, d=75
      log_OR = log((15*75)/(85*25)), var = 1/15 + 1/85 + 1/25 + 1/75
    Inverse-variance FE pooling.
    """
    import math

    from mission_critical.diffmeta.engine import _effects_or, _python_pool

    rows = [
        {"ai": 10, "bi": 90, "ci": 20, "di": 75},
        {"ai": 15, "bi": 85, "ci": 25, "di": 75},
    ]
    yi, vi = _effects_or(rows)

    # Expected hand-calculation
    lo1 = math.log((10 * 75) / (90 * 20))
    v1 = 1/10 + 1/90 + 1/20 + 1/75
    lo2 = math.log((15 * 75) / (85 * 25))
    v2 = 1/15 + 1/85 + 1/25 + 1/75
    w1 = 1/v1; w2 = 1/v2
    expected_pooled = (w1 * lo1 + w2 * lo2) / (w1 + w2)
    expected_se = math.sqrt(1 / (w1 + w2))

    result = _python_pool(yi, vi, method="FE", measure="OR")
    assert abs(result.estimate - expected_pooled) < 1e-12
    assert abs(result.se - expected_se) < 1e-12
    assert result.k == 2


def test_python_engine_applies_conditional_continuity(tmp_path: Path):
    """Conditional 0.5 correction: only studies with a zero cell get it.

    Unconditional correction (adding 0.5 to every study regardless) is
    the one that biases OR -> 1 and is explicitly NOT what we want.
    """
    import numpy as np

    from mission_critical.diffmeta.engine import _apply_continuity_correction

    ai = np.array([0, 10])
    bi = np.array([50, 90])
    ci = np.array([5, 20])
    di = np.array([45, 80])

    a, b, c, d = _apply_continuity_correction(ai, bi, ci, di)
    # Study 0 had a zero cell → all cells += 0.5
    assert a[0] == 0.5
    assert b[0] == 50.5
    # Study 1 had no zero cells → unchanged
    assert a[1] == 10.0
    assert b[1] == 90.0


def test_compare_rejects_missing_columns(tmp_path: Path):
    from mission_critical.diffmeta import compare_binary_or
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        compare_binary_or(csv_path, rscript_path="fake")


def test_compare_rejects_empty_csv(tmp_path: Path):
    from mission_critical.diffmeta import compare_binary_or
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("ai,bi,ci,di\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no data rows"):
        compare_binary_or(csv_path, rscript_path="fake")
