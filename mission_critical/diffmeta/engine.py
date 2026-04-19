"""Binary-outcome fixed-effect OR meta-analysis: Python vs R metafor.

Implementation choices:
- Effect measure: log-OR (log odds ratio). Pool via fixed-effects
  inverse-variance weighting. Random-effects (DL/REML/HKSJ) out of
  scope for v0.1 — those have more engine-specific knobs.
- Continuity correction: add 0.5 to each cell of a study with any
  zero cell (per Cochrane Handbook). Unconditional correction
  (adding 0.5 to every study regardless of zeros) is explicitly
  avoided — that biases OR toward 1 (lessons.md).
- Python impl is direct numpy (no scipy dependency) so the
  difference isn't "two libraries that both call LAPACK" — it's
  genuinely independent code paths.
"""
from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np


DEFAULT_RSCRIPT = (
    r"C:/Program Files/R/R-4.5.2/bin/Rscript.exe"
    if sys.platform == "win32" else "Rscript"
)

DEFAULT_TOLERANCE = 1e-6


@dataclass(frozen=True)
class PooledResult:
    """Fixed-effects pooled log-OR result."""
    log_or: float
    se: float
    ci_lower: float
    ci_upper: float
    z: float
    q: float
    k: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ComparisonResult:
    python: PooledResult
    r: PooledResult
    tolerance: float
    max_abs_diff: float
    diverges: bool
    field_diffs: dict[str, float]

    def to_dict(self) -> dict:
        return {
            "python": self.python.to_dict(),
            "r": self.r.to_dict(),
            "tolerance": self.tolerance,
            "max_abs_diff": self.max_abs_diff,
            "diverges": self.diverges,
            "field_diffs": self.field_diffs,
        }


def _apply_continuity_correction(
    ai: np.ndarray, bi: np.ndarray, ci: np.ndarray, di: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Add 0.5 to each cell of a study if ANY of its cells is zero.

    Conditional correction (per Cochrane Handbook). Unconditional
    correction biases OR toward 1 — explicitly not done here.
    """
    has_zero = (ai == 0) | (bi == 0) | (ci == 0) | (di == 0)
    a = ai.astype(float).copy()
    b = bi.astype(float).copy()
    c = ci.astype(float).copy()
    d = di.astype(float).copy()
    a[has_zero] += 0.5
    b[has_zero] += 0.5
    c[has_zero] += 0.5
    d[has_zero] += 0.5
    return a, b, c, d


def _python_fe_or(
    ai: np.ndarray, bi: np.ndarray, ci: np.ndarray, di: np.ndarray,
) -> PooledResult:
    """Fixed-effect inverse-variance pooled log-OR — direct numpy impl."""
    a, b, c, d = _apply_continuity_correction(ai, bi, ci, di)
    log_or_i = np.log((a * d) / (b * c))
    var_i = 1.0 / a + 1.0 / b + 1.0 / c + 1.0 / d
    w_i = 1.0 / var_i
    W = float(w_i.sum())
    pooled = float((w_i * log_or_i).sum() / W)
    se = float(math.sqrt(1.0 / W))
    z_crit = 1.959963984540054  # qnorm(0.975) to 15 decimal places
    ci_lo = pooled - z_crit * se
    ci_hi = pooled + z_crit * se
    z = pooled / se
    # Cochran's Q (heterogeneity statistic)
    q = float(((log_or_i - pooled) ** 2 * w_i).sum())
    return PooledResult(
        log_or=pooled, se=se, ci_lower=ci_lo, ci_upper=ci_hi,
        z=z, q=q, k=int(len(ai)),
    )


_RSCRIPT_FE_OR = r"""
suppressMessages(library(metafor))
args <- commandArgs(trailingOnly = TRUE)
csv_path <- args[1]
d <- read.csv(csv_path, stringsAsFactors = FALSE)
# expected columns: ai, bi, ci, di
res <- rma.uni(
    ai = d$ai, bi = d$bi, ci = d$ci, di = d$di,
    measure = "OR", method = "FE",
    add = 0.5, to = "only0"
)
out <- list(
    log_or = as.numeric(res$b),
    se = as.numeric(res$se),
    ci_lower = as.numeric(res$ci.lb),
    ci_upper = as.numeric(res$ci.ub),
    z = as.numeric(res$zval),
    q = as.numeric(res$QE),
    k = as.integer(res$k)
)
cat(toJSON(out, digits = 20), "\n", sep = "")
"""


def _r_fe_or(
    ai: np.ndarray, bi: np.ndarray, ci: np.ndarray, di: np.ndarray,
    rscript_path: str,
) -> PooledResult:
    """Same model via R metafor — independent implementation."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        csv_path = tmp_path / "input.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ai", "bi", "ci", "di"])
            for row in zip(ai.tolist(), bi.tolist(), ci.tolist(), di.tolist()):
                w.writerow(row)

        script_path = tmp_path / "run.R"
        # Prepend the toJSON loader since metafor doesn't ship jsonlite.
        script_path.write_text(
            'suppressMessages(library(jsonlite))\n' + _RSCRIPT_FE_OR,
            encoding="utf-8",
        )

        try:
            proc = subprocess.run(
                [rscript_path, str(script_path), str(csv_path)],
                capture_output=True, text=True, timeout=60, check=False,
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
    return PooledResult(
        log_or=float(payload["log_or"][0] if isinstance(payload["log_or"], list) else payload["log_or"]),
        se=float(payload["se"][0] if isinstance(payload["se"], list) else payload["se"]),
        ci_lower=float(payload["ci_lower"][0] if isinstance(payload["ci_lower"], list) else payload["ci_lower"]),
        ci_upper=float(payload["ci_upper"][0] if isinstance(payload["ci_upper"], list) else payload["ci_upper"]),
        z=float(payload["z"][0] if isinstance(payload["z"], list) else payload["z"]),
        q=float(payload["q"][0] if isinstance(payload["q"], list) else payload["q"]),
        k=int(payload["k"][0] if isinstance(payload["k"], list) else payload["k"]),
    )


def compare_binary_or(
    csv_path: Path | str,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    rscript_path: Optional[str] = None,
) -> ComparisonResult:
    """Run both engines on the same CSV; return a comparison record.

    CSV must have columns ai, bi, ci, di (treatment-event, treatment-no-
    event, control-event, control-no-event counts per study).
    """
    csv_path = Path(csv_path)
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        raise ValueError(f"CSV has no data rows: {csv_path}")

    required = {"ai", "bi", "ci", "di"}
    missing = required - set(rows[0].keys())
    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")

    ai = np.array([int(r["ai"]) for r in rows], dtype=np.int64)
    bi = np.array([int(r["bi"]) for r in rows], dtype=np.int64)
    ci = np.array([int(r["ci"]) for r in rows], dtype=np.int64)
    di = np.array([int(r["di"]) for r in rows], dtype=np.int64)

    if rscript_path is None:
        rscript_path = os.environ.get("RSCRIPT_PATH", DEFAULT_RSCRIPT)

    py = _python_fe_or(ai, bi, ci, di)
    r = _r_fe_or(ai, bi, ci, di, rscript_path=rscript_path)

    fields = ("log_or", "se", "ci_lower", "ci_upper", "z", "q")
    diffs = {f: abs(getattr(py, f) - getattr(r, f)) for f in fields}
    max_diff = max(diffs.values())
    diverges = max_diff > tolerance

    return ComparisonResult(
        python=py, r=r, tolerance=tolerance,
        max_abs_diff=max_diff, diverges=diverges,
        field_diffs=diffs,
    )
