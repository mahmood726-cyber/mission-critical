"""Random-effects + new-measure tests for diffmeta.

Exercises the full {OR, SMD, GEN} x {FE, DL, REML, HKSJ} matrix against
metafor 4.8. Tolerance 1e-6 on every numeric field (estimate, SE, CI,
z/t, Q, tau2, I^2).

Skipped when R / metafor isn't available.
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
    env = os.environ.get("RSCRIPT_PATH")
    if env and shutil.which(env):
        return env
    candidates = []
    if sys.platform == "win32":
        candidates.append(r"C:/Program Files/R/R-4.5.2/bin/Rscript.exe")
        candidates.append(r"C:/Program Files/R/R-4.5.1/bin/Rscript.exe")
    candidates.append(shutil.which("Rscript"))
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


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
    reason="R + metafor not available (expected — diffmeta is a local-only tool)",
)


# --- fixtures ----------------------------------------------------------

_OR_ROWS = [
    {"ai": 10, "bi": 90, "ci": 20, "di": 80},
    {"ai": 5,  "bi": 45, "ci": 10, "di": 40},
    {"ai": 15, "bi": 85, "ci": 25, "di": 75},
    {"ai": 8,  "bi": 92, "ci": 12, "di": 88},
    {"ai": 20, "bi": 80, "ci": 30, "di": 70},
    {"ai": 25, "bi": 75, "ci": 18, "di": 82},
    {"ai": 12, "bi": 88, "ci": 14, "di": 86},
    {"ai": 9,  "bi": 91, "ci": 17, "di": 83},
]


_SMD_ROWS = [
    # Hedges-Olkin-like: (n1, m1, sd1, n2, m2, sd2)
    {"n1i": 30, "m1i": 10.2, "sd1i": 3.1, "n2i": 30, "m2i": 8.7, "sd2i": 3.4},
    {"n1i": 45, "m1i": 11.5, "sd1i": 2.8, "n2i": 45, "m2i": 9.1, "sd2i": 3.0},
    {"n1i": 60, "m1i": 9.8,  "sd1i": 3.5, "n2i": 60, "m2i": 8.2, "sd2i": 3.2},
    {"n1i": 25, "m1i": 12.3, "sd1i": 4.0, "n2i": 25, "m2i": 10.1,"sd2i": 3.8},
    {"n1i": 50, "m1i": 10.9, "sd1i": 2.5, "n2i": 50, "m2i": 9.4, "sd2i": 2.7},
]


_GEN_ROWS = [
    # Pre-computed effect + variance. Any scale.
    {"yi": -0.41, "vi": 0.016},
    {"yi": -0.33, "vi": 0.022},
    {"yi": -0.58, "vi": 0.030},
    {"yi": -0.12, "vi": 0.018},
    {"yi": -0.47, "vi": 0.025},
    {"yi": -0.21, "vi": 0.020},
]


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError("need at least one row")
    path.write_text("", encoding="utf-8")  # create
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=sorted(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


# --- parametrized matrix ------------------------------------------------

@skip_if_no_r
@pytest.mark.parametrize("method", ["FE", "DL", "REML", "HKSJ"])
def test_or_pooling_matches_metafor(tmp_path: Path, method: str):
    from mission_critical.diffmeta import compare
    csv_path = tmp_path / "or.csv"
    _write_csv(csv_path, _OR_ROWS)
    res = compare(csv_path, measure="OR", method=method, rscript_path=_RSCRIPT)
    assert res.diverges is False, (
        f"OR/{method} disagreement: {res.field_diffs}\n"
        f"python={res.python}\nR={res.r}"
    )


@skip_if_no_r
@pytest.mark.parametrize("method", ["FE", "DL", "REML", "HKSJ"])
def test_smd_pooling_matches_metafor(tmp_path: Path, method: str):
    from mission_critical.diffmeta import compare
    csv_path = tmp_path / "smd.csv"
    _write_csv(csv_path, _SMD_ROWS)
    res = compare(csv_path, measure="SMD", method=method, rscript_path=_RSCRIPT)
    assert res.diverges is False, (
        f"SMD/{method} disagreement: {res.field_diffs}\n"
        f"python={res.python}\nR={res.r}"
    )


@skip_if_no_r
@pytest.mark.parametrize("method", ["FE", "DL", "REML", "HKSJ"])
def test_gen_pooling_matches_metafor(tmp_path: Path, method: str):
    from mission_critical.diffmeta import compare
    csv_path = tmp_path / "gen.csv"
    _write_csv(csv_path, _GEN_ROWS)
    res = compare(csv_path, measure="GEN", method=method, rscript_path=_RSCRIPT)
    assert res.diverges is False, (
        f"GEN/{method} disagreement: {res.field_diffs}\n"
        f"python={res.python}\nR={res.r}"
    )


# --- unit-level tests (no R required) -----------------------------------

def test_smd_effects_match_hand_calc():
    """Hedges' g with EXACT gamma J correction — matches metafor."""
    import math

    from mission_critical.diffmeta.engine import _effects_smd
    from scipy.special import gammaln

    row = {"n1i": 30, "m1i": 10.2, "sd1i": 3.1, "n2i": 30, "m2i": 8.7, "sd2i": 3.4}
    yi, vi = _effects_smd([row])

    # Hand calc using exact gamma-ratio J
    n1, m1, sd1, n2, m2, sd2 = 30, 10.2, 3.1, 30, 8.7, 3.4
    df = n1 + n2 - 2
    s_pool = math.sqrt(((n1 - 1) * sd1**2 + (n2 - 1) * sd2**2) / df)
    d = (m1 - m2) / s_pool
    log_J = gammaln(df / 2) - 0.5 * math.log(df / 2) - gammaln((df - 1) / 2)
    J = math.exp(log_J)
    g = J * d
    expected_v = 1.0 / n1 + 1.0 / n2 + g**2 / (2.0 * (n1 + n2))

    assert abs(float(yi[0]) - g) < 1e-12
    assert abs(float(vi[0]) - expected_v) < 1e-12


def test_tau2_dl_zero_when_no_heterogeneity():
    """When Q <= k-1, DL tau^2 floors at 0 — canonical Cochrane behavior."""
    import numpy as np
    from mission_critical.diffmeta.engine import _tau2_dl

    # 3 studies with identical y and v = identical weights = Q=0
    yi = np.array([0.5, 0.5, 0.5])
    vi = np.array([0.02, 0.02, 0.02])
    assert _tau2_dl(yi, vi) == 0.0


def test_tau2_reml_positive_on_heterogeneous():
    """REML tau^2 should be > 0 when studies clearly disagree."""
    import numpy as np
    from mission_critical.diffmeta.engine import _tau2_reml

    yi = np.array([-0.8, -0.1, 0.3, 0.9])
    vi = np.array([0.04, 0.03, 0.04, 0.05])
    tau2 = _tau2_reml(yi, vi)
    assert tau2 > 0.0


def test_hksj_uses_t_distribution():
    """HKSJ pooled result carries the uses_t_distribution flag."""
    from mission_critical.diffmeta.engine import _effects_gen, _python_pool

    rows = [{"yi": y, "vi": v} for y, v in
            [(-0.4, 0.02), (-0.3, 0.03), (-0.5, 0.02), (-0.1, 0.04)]]
    yi, vi = _effects_gen(rows)
    result = _python_pool(yi, vi, method="HKSJ", measure="GEN")
    assert result.uses_t_distribution is True
    assert result.method == "HKSJ"


def test_fe_result_has_zero_tau2_and_i2():
    """FE pooling must produce tau2=0 and treat i2 consistently."""
    from mission_critical.diffmeta.engine import _effects_gen, _python_pool
    rows = [{"yi": y, "vi": v} for y, v in
            [(-0.4, 0.02), (-0.3, 0.03), (-0.5, 0.02)]]
    yi, vi = _effects_gen(rows)
    result = _python_pool(yi, vi, method="FE", measure="GEN")
    assert result.tau2 == 0.0
    assert result.method == "FE"
    assert result.uses_t_distribution is False
