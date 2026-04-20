"""Differential-engine meta-analysis verifier.

Runs the same meta-analysis in two independent engines — a pure-numpy
Python implementation and R metafor — and flags any divergence above
tolerance. The Python side is written from formulas (no metafor
binding) so differences reflect genuinely independent code paths, not
two shared-backend libraries.

## Supported matrix (v0.2)

Effect measures:
  - OR   — log odds ratio, from 2x2 binary counts (ai, bi, ci, di)
  - SMD  — Hedges' g standardized mean difference, from (n, m, sd) per group
  - GEN  — generic inverse-variance: user supplies (yi, vi) directly

Pooling methods:
  - FE    — fixed-effects inverse variance
  - DL    — DerSimonian-Laird random-effects (closed form, biased at k<10)
  - REML  — restricted maximum likelihood random-effects (gold standard for k<30)
  - HKSJ  — Knapp-Hartung-Sidik-Jonkman on REML tau^2; t-distribution CIs

Any {measure} x {method} combination is supported — 12 total. See
tests/test_diffmeta_re.py and tests/test_diffmeta_measures.py for
hand-checked fixtures against metafor 4.8.

## Continuity correction

For binary with zero cells, apply 0.5 to each cell of the affected
study only (conditional correction, Cochrane Handbook). Unconditional
correction biases OR -> 1 (lessons.md) and is explicitly not used.

## Implementation notes

- Python side uses numpy + scipy.optimize.minimize_scalar for REML.
- R side invokes metafor::rma with measure + method + test="knha"
  for HKSJ, via Rscript subprocess.
- Comparison fields: pooled estimate (log_or / smd / y), SE, CI bounds,
  Q, tau2 (RE only), I^2 (RE only), k.
"""
from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Optional

import numpy as np
from scipy import optimize
from scipy import stats
from scipy.special import gammaln

from mission_critical.tolerance_config import ToleranceConfig


Measure = Literal["OR", "SMD", "GEN"]
Method = Literal["FE", "DL", "REML", "HKSJ"]

DEFAULT_RSCRIPT = (
    r"C:/Program Files/R/R-4.5.2/bin/Rscript.exe"
    if sys.platform == "win32" else "Rscript"
)
DEFAULT_TOLERANCE = 1e-6

# z-critical for 95% CI (two-sided, same to 15 decimals as R qnorm(0.975))
Z_95 = 1.959963984540054


# =====================================================================
# Effect-size computation: raw data -> (yi, vi)
# =====================================================================

def _apply_continuity_correction(
    ai: np.ndarray, bi: np.ndarray, ci: np.ndarray, di: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Add 0.5 to each cell of a study IFF that study has any zero cell.

    Conditional correction (Cochrane Handbook). Unconditional
    correction biases OR -> 1 and is explicitly not what we want.
    """
    has_zero = (ai == 0) | (bi == 0) | (ci == 0) | (di == 0)
    a = ai.astype(float).copy()
    b = bi.astype(float).copy()
    c = ci.astype(float).copy()
    d = di.astype(float).copy()
    a[has_zero] += 0.5; b[has_zero] += 0.5
    c[has_zero] += 0.5; d[has_zero] += 0.5
    return a, b, c, d


def _effects_or(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Log-OR from 2x2 counts, with 0.5 conditional correction."""
    ai = np.array([int(r["ai"]) for r in rows], dtype=np.int64)
    bi = np.array([int(r["bi"]) for r in rows], dtype=np.int64)
    ci = np.array([int(r["ci"]) for r in rows], dtype=np.int64)
    di = np.array([int(r["di"]) for r in rows], dtype=np.int64)
    a, b, c, d = _apply_continuity_correction(ai, bi, ci, di)
    yi = np.log((a * d) / (b * c))
    vi = 1.0 / a + 1.0 / b + 1.0 / c + 1.0 / d
    return yi, vi


def _effects_smd(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Hedges' g SMD with small-sample J correction.

    Columns: n1i, m1i, sd1i, n2i, m2i, sd2i (metafor names).
    Formulas follow Hedges (1981) / Hedges & Olkin (1985).
    """
    n1 = np.array([float(r["n1i"]) for r in rows])
    m1 = np.array([float(r["m1i"]) for r in rows])
    sd1 = np.array([float(r["sd1i"]) for r in rows])
    n2 = np.array([float(r["n2i"]) for r in rows])
    m2 = np.array([float(r["m2i"]) for r in rows])
    sd2 = np.array([float(r["sd2i"]) for r in rows])

    df = n1 + n2 - 2
    s_pool = np.sqrt(((n1 - 1) * sd1**2 + (n2 - 1) * sd2**2) / df)
    d = (m1 - m2) / s_pool
    # J correction (unbiased Hedges' g). metafor uses the EXACT form
    # via log-gamma, not the 1 - 3/(4*df - 1) approximation; use the
    # exact form for cross-engine match at small df.
    #   J(df) = Γ(df/2) / (sqrt(df/2) * Γ((df-1)/2))
    log_J = gammaln(df / 2.0) - 0.5 * np.log(df / 2.0) - gammaln((df - 1) / 2.0)
    J = np.exp(log_J)
    yi = J * d
    # Approx variance of Hedges' g (metafor's default)
    vi = 1.0 / n1 + 1.0 / n2 + yi**2 / (2.0 * (n1 + n2))
    return yi, vi


def _effects_gen(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Generic inverse variance: user supplies (yi, vi) per study."""
    yi = np.array([float(r["yi"]) for r in rows])
    vi = np.array([float(r["vi"]) for r in rows])
    return yi, vi


_EFFECT_FNS = {"OR": _effects_or, "SMD": _effects_smd, "GEN": _effects_gen}
_REQUIRED_COLS = {
    "OR":  {"ai", "bi", "ci", "di"},
    "SMD": {"n1i", "m1i", "sd1i", "n2i", "m2i", "sd2i"},
    "GEN": {"yi", "vi"},
}


# =====================================================================
# Pooling: (yi, vi) -> PooledResult
# =====================================================================

@dataclass(frozen=True)
class PooledResult:
    estimate: float        # pooled effect (log-OR / SMD / y)
    se: float
    ci_lower: float
    ci_upper: float
    z_or_t: float          # z for FE/DL, z for HKSJ is actually t
    q: float               # Cochran's Q (homogeneity)
    tau2: float            # 0 for FE
    i2: float              # 0 for FE
    k: int
    method: str
    measure: str
    # Flag: HKSJ uses t-distribution; everything else uses z.
    uses_t_distribution: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _cochrans_q(yi: np.ndarray, vi: np.ndarray) -> tuple[float, float]:
    """Cochran's Q using FE weights; return (Q, y_bar_FE)."""
    w_fe = 1.0 / vi
    y_fe = float((w_fe * yi).sum() / w_fe.sum())
    q = float((w_fe * (yi - y_fe) ** 2).sum())
    return q, y_fe


def _tau2_dl(yi: np.ndarray, vi: np.ndarray) -> float:
    """DerSimonian-Laird moment estimator for tau^2."""
    k = len(yi)
    if k < 2:
        return 0.0
    w = 1.0 / vi
    q, _ = _cochrans_q(yi, vi)
    # c = sum(w) - sum(w^2) / sum(w)
    c = float(w.sum() - (w * w).sum() / w.sum())
    tau2 = (q - (k - 1)) / c if c > 0 else 0.0
    return max(0.0, tau2)


def _tau2_reml(yi: np.ndarray, vi: np.ndarray) -> float:
    """REML estimator of tau^2 via minimize_scalar on -logLik_REML.

    Closed-form log-likelihood (up to additive constants):
      logLik(tau2) = -0.5 * [
            sum(log(v_i + tau2))
          + log(sum(1/(v_i + tau2)))
          + sum((y_i - y_bar(tau2))^2 / (v_i + tau2))
        ]
    where y_bar(tau2) = sum(w_i y_i) / sum(w_i), w_i = 1/(v_i + tau2).
    """
    k = len(yi)
    if k < 2:
        return 0.0

    def neg_log_lik(tau2: float) -> float:
        if tau2 < 0:
            return float("inf")
        v_eff = vi + tau2
        w = 1.0 / v_eff
        y_bar = float((w * yi).sum() / w.sum())
        term1 = float(np.log(v_eff).sum())
        term2 = float(math.log(w.sum()))
        term3 = float(((yi - y_bar) ** 2 / v_eff).sum())
        return 0.5 * (term1 + term2 + term3)

    # Bounded search in [0, 100 * max(vi)]. tau2 rarely exceeds the
    # largest within-study variance in practice. xatol tightened to
    # 1e-14 to match metafor's default REML convergence (needed for
    # HKSJ CI agreement at 1e-6 tolerance).
    upper = max(100.0 * float(vi.max()), 1.0)
    result = optimize.minimize_scalar(
        neg_log_lik, bounds=(0.0, upper), method="bounded",
        options={"xatol": 1e-14},
    )
    return max(0.0, float(result.x))


def _pool_with_tau2(
    yi: np.ndarray, vi: np.ndarray, tau2: float,
    *, method_name: str, measure: str, use_knha: bool = False,
) -> PooledResult:
    """Pool given a tau2 (FE uses tau2=0). Optionally apply HKSJ SE."""
    k = len(yi)
    v_eff = vi + tau2
    w = 1.0 / v_eff
    W = float(w.sum())
    estimate = float((w * yi).sum() / W)

    # Standard SE (inverse-variance)
    se_iv = float(math.sqrt(1.0 / W))

    # Cochran's Q (homogeneity) uses FE weights regardless of tau2.
    q, _ = _cochrans_q(yi, vi)
    # I^2 via metafor's formulation: 100 * tau^2 / (tau^2 + v_typ)
    # where v_typ is the typical within-study variance (Higgins 2002):
    #   v_typ = (k-1) * Σw / (Σw)^2 - Σw^2)   using FE weights w = 1/v
    # This differs from the older (Q - df)/Q form; metafor uses this
    # so cross-engine match requires it.
    if k < 2 or tau2 <= 0.0:
        i2 = 0.0
    else:
        w_fe = 1.0 / vi
        denom = float((w_fe.sum()) ** 2 - (w_fe ** 2).sum())
        if denom > 0:
            v_typ = (k - 1) * float(w_fe.sum()) / denom
            i2 = 100.0 * tau2 / (tau2 + v_typ)
        else:
            i2 = 0.0

    if use_knha and k >= 2:
        # Knapp-Hartung-Sidik-Jonkman: se = sqrt(sum(w_i (y_i - est)^2) / ((k-1) W))
        se = float(math.sqrt(
            (w * (yi - estimate) ** 2).sum() / ((k - 1) * W)
        ))
        # t-distribution with df = k-1 for CI
        tcrit = float(stats.t.ppf(0.975, df=k - 1))
        ci_lo = estimate - tcrit * se
        ci_hi = estimate + tcrit * se
        z_or_t = estimate / se
        uses_t = True
    else:
        se = se_iv
        ci_lo = estimate - Z_95 * se
        ci_hi = estimate + Z_95 * se
        z_or_t = estimate / se
        uses_t = False

    return PooledResult(
        estimate=estimate, se=se, ci_lower=ci_lo, ci_upper=ci_hi,
        z_or_t=z_or_t, q=q, tau2=float(tau2), i2=float(i2), k=k,
        method=method_name, measure=measure, uses_t_distribution=uses_t,
    )


def _python_pool(
    yi: np.ndarray, vi: np.ndarray, *, method: Method, measure: str,
) -> PooledResult:
    if method == "FE":
        return _pool_with_tau2(yi, vi, 0.0, method_name="FE", measure=measure)
    if method == "DL":
        tau2 = _tau2_dl(yi, vi)
        return _pool_with_tau2(yi, vi, tau2, method_name="DL", measure=measure)
    if method == "REML":
        tau2 = _tau2_reml(yi, vi)
        return _pool_with_tau2(yi, vi, tau2, method_name="REML", measure=measure)
    if method == "HKSJ":
        tau2 = _tau2_reml(yi, vi)  # HKSJ on REML tau^2 (metafor default)
        return _pool_with_tau2(
            yi, vi, tau2, method_name="HKSJ", measure=measure, use_knha=True,
        )
    raise ValueError(f"unknown method: {method!r}")


# =====================================================================
# R backend: metafor via Rscript subprocess
# =====================================================================

_RSCRIPT_TEMPLATE = r"""
suppressMessages(library(metafor))
suppressMessages(library(jsonlite))
args <- commandArgs(trailingOnly = TRUE)
csv_path <- args[1]
measure <- args[2]
method <- args[3]
use_knha <- args[4] == "TRUE"

d <- read.csv(csv_path, stringsAsFactors = FALSE)

if (measure == "OR") {
    res <- rma.uni(
        ai = d$ai, bi = d$bi, ci = d$ci, di = d$di,
        measure = "OR", method = method,
        add = 0.5, to = "only0",
        test = if (use_knha) "knha" else "z"
    )
} else if (measure == "SMD") {
    res <- rma.uni(
        m1i = d$m1i, sd1i = d$sd1i, n1i = d$n1i,
        m2i = d$m2i, sd2i = d$sd2i, n2i = d$n2i,
        measure = "SMD", method = method,
        test = if (use_knha) "knha" else "z"
    )
} else if (measure == "GEN") {
    res <- rma.uni(
        yi = d$yi, vi = d$vi,
        measure = "GEN", method = method,
        test = if (use_knha) "knha" else "z"
    )
} else {
    stop(paste("unknown measure:", measure))
}

out <- list(
    estimate = as.numeric(res$b),
    se = as.numeric(res$se),
    ci_lower = as.numeric(res$ci.lb),
    ci_upper = as.numeric(res$ci.ub),
    z_or_t = as.numeric(res$zval),
    q = as.numeric(res$QE),
    tau2 = as.numeric(if (method == "FE") 0 else res$tau2),
    i2 = as.numeric(if (method == "FE") 0 else res$I2),
    k = as.integer(res$k),
    method = method,
    measure = measure,
    uses_t = use_knha
)
cat(toJSON(out, digits = 20), "\n", sep = "")
"""


def _r_pool(
    rows: list[dict], measure: Measure, method: Method, rscript_path: str,
) -> PooledResult:
    """Run the same (measure, method) in R metafor."""
    # HKSJ is implemented as method=REML + test="knha" in metafor.
    r_method = "REML" if method == "HKSJ" else method
    use_knha = method == "HKSJ"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        csv_path = tmp_path / "input.csv"
        cols = sorted(_REQUIRED_COLS[measure])
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for row in rows:
                w.writerow([row[c] for c in cols])

        script_path = tmp_path / "run.R"
        script_path.write_text(_RSCRIPT_TEMPLATE, encoding="utf-8")

        try:
            proc = subprocess.run(
                [rscript_path, str(script_path), str(csv_path),
                 measure, r_method, "TRUE" if use_knha else "FALSE"],
                capture_output=True, text=True, timeout=120, check=False,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                f"Rscript not found at {rscript_path!r}. "
                "Set RSCRIPT_PATH env var or install R + metafor."
            ) from e

        if proc.returncode != 0:
            raise RuntimeError(
                f"Rscript failed (exit {proc.returncode}):\n"
                f"STDERR: {proc.stderr}\nSTDOUT: {proc.stdout}"
            )
        last_line = proc.stdout.strip().splitlines()[-1]
        payload = json.loads(last_line)

    def _first(x):
        return float(x[0] if isinstance(x, list) else x)

    return PooledResult(
        estimate=_first(payload["estimate"]),
        se=_first(payload["se"]),
        ci_lower=_first(payload["ci_lower"]),
        ci_upper=_first(payload["ci_upper"]),
        z_or_t=_first(payload["z_or_t"]),
        q=_first(payload["q"]),
        tau2=_first(payload["tau2"]),
        i2=_first(payload["i2"]),
        k=int(payload["k"][0] if isinstance(payload["k"], list) else payload["k"]),
        method=method,
        measure=measure,
        uses_t_distribution=bool(use_knha),
    )


# =====================================================================
# Top-level compare
# =====================================================================

@dataclass
class ComparisonResult:
    python: PooledResult
    r: PooledResult
    tolerance: float
    max_abs_diff: float
    diverges: bool
    field_diffs: dict[str, float]
    measure: str
    method: str

    def to_dict(self) -> dict:
        return {
            "python": self.python.to_dict(),
            "r": self.r.to_dict(),
            "tolerance": self.tolerance,
            "max_abs_diff": self.max_abs_diff,
            "diverges": self.diverges,
            "field_diffs": self.field_diffs,
            "measure": self.measure,
            "method": self.method,
        }


def _read_rows(csv_path: Path) -> list[dict]:
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        raise ValueError(f"CSV has no data rows: {csv_path}")
    return rows


# Per-field tolerance scaling. metafor uses Fisher scoring for REML
# (~1e-8 convergence); scipy's Brent-scalar optimizer hits ~1e-7.
# That noise compounds in derived fields — a ~1e-7 diff in tau^2
# propagates to ~1e-6 in SE/CI (via sqrt(1/Σ w_i*)) and ~1e-4 in I^2
# (which is on the percentage-point scale). Tightening the Python
# optimizer below 1e-7 requires reimplementing metafor's Fisher
# scoring — out of scope. Instead, report a per-field tolerance
# multiplier that reflects the propagation structure.
#
# For FE and DL (closed-form), all fields should agree to the base
# tolerance. For REML/HKSJ, SE/CI/z compound the tau^2 noise; accept
# up to 10x. tau^2 and I^2 themselves are on larger scales, so get
# 100x and 1e4x multipliers.
_FIELD_TOLERANCE_MULTIPLIERS_RE = {
    "se": 10.0,
    "ci_lower": 10.0,
    "ci_upper": 10.0,
    "z_or_t": 10.0,
    "tau2": 100.0,
    "i2": 1.0e4,
}
_FIELD_TOLERANCE_MULTIPLIERS_FE = {
    # FE/DL are closed-form; all fields strict.
}


def compare(
    csv_path: Path | str,
    *,
    measure: Measure = "OR",
    method: Method = "FE",
    tolerance: float = DEFAULT_TOLERANCE,
    rscript_path: Optional[str] = None,
    tolerance_config: Optional[ToleranceConfig] = None,
) -> ComparisonResult:
    """Run both engines on the same CSV and compare their output.

    Tolerance behavior:
      - If `tolerance_config` is supplied, its per-measure/per-method/
        per-field multipliers are used. See `tolerance_config` module.
      - Otherwise falls back to the legacy built-in multipliers: FE/DL
        strict at `tolerance`; REML/HKSJ get scaled tolerances on
        SE/CI/z (10x) and tau^2/I^2 (100x/10000x) to absorb scipy-vs-
        metafor REML optimizer precision.
    """
    csv_path = Path(csv_path)
    rows = _read_rows(csv_path)

    required = _REQUIRED_COLS[measure]
    missing = required - set(rows[0].keys())
    if missing:
        raise ValueError(
            f"CSV missing required columns for measure={measure}: "
            f"{sorted(missing)} (need {sorted(required)})"
        )

    yi, vi = _EFFECT_FNS[measure](rows)
    py = _python_pool(yi, vi, method=method, measure=measure)

    if rscript_path is None:
        rscript_path = os.environ.get("RSCRIPT_PATH", DEFAULT_RSCRIPT)
    r = _r_pool(rows, measure, method, rscript_path)

    fields = ("estimate", "se", "ci_lower", "ci_upper", "z_or_t",
              "q", "tau2", "i2")
    # Either use the supplied ToleranceConfig or fall back to built-in
    # multipliers (legacy path).
    if tolerance_config is not None:
        # ToleranceConfig's base_tolerance overrides caller's `tolerance`
        # unless the caller supplied a non-default tolerance explicitly.
        def _tol(field_name: str) -> float:
            return tolerance_config.tolerance_for(field_name, measure, method)
    else:
        legacy_mults = (
            _FIELD_TOLERANCE_MULTIPLIERS_RE
            if method in ("REML", "HKSJ")
            else _FIELD_TOLERANCE_MULTIPLIERS_FE
        )
        def _tol(field_name: str) -> float:
            return tolerance * legacy_mults.get(field_name, 1.0)

    diffs: dict[str, float] = {}
    diverges = False
    for f in fields:
        d = abs(getattr(py, f) - getattr(r, f))
        diffs[f] = d
        field_tol = _tol(f)
        if d > field_tol:
            diverges = True

    # Report raw max diff (human-readable) not scaled
    max_diff = max(diffs.values())

    return ComparisonResult(
        python=py, r=r, tolerance=tolerance,
        max_abs_diff=max_diff, diverges=diverges, field_diffs=diffs,
        measure=measure, method=method,
    )


# ---------------------------------------------------------------------
# Backward-compat alias
# ---------------------------------------------------------------------
def compare_binary_or(
    csv_path: Path | str,
    *, tolerance: float = DEFAULT_TOLERANCE,
    rscript_path: Optional[str] = None,
) -> ComparisonResult:
    """Backward-compat: OR + FE. Equivalent to `compare(..., measure='OR', method='FE')`."""
    return compare(
        csv_path, measure="OR", method="FE",
        tolerance=tolerance, rscript_path=rscript_path,
    )
