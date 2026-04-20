"""diffmeta CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from mission_critical.diffmeta.engine import (
    DEFAULT_TOLERANCE,
    compare,
)
from mission_critical.tolerance_config import ToleranceConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="diffmeta",
        description="Differential-engine meta-analysis verifier (Python vs R metafor).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    cmp_p = sub.add_parser(
        "compare",
        help="Run both engines on a CSV; exit non-zero on divergence.",
    )
    cmp_p.add_argument("csv", type=Path, help="CSV with required columns for the measure.")
    cmp_p.add_argument(
        "--measure", choices=["OR", "SMD", "GEN"], default="OR",
        help="Effect measure (default OR). "
             "OR needs ai/bi/ci/di; SMD needs n1i/m1i/sd1i/n2i/m2i/sd2i; "
             "GEN needs yi/vi.",
    )
    cmp_p.add_argument(
        "--method", choices=["FE", "DL", "REML", "HKSJ"], default="FE",
        help="Pooling method (default FE). HKSJ uses REML tau^2 + Knapp-Hartung.",
    )
    cmp_p.add_argument(
        "--tolerance", type=float, default=DEFAULT_TOLERANCE,
        help=f"Maximum allowed abs diff across fields (default {DEFAULT_TOLERANCE:g}).",
    )
    cmp_p.add_argument(
        "--rscript", default=None,
        help="Path to Rscript executable (else RSCRIPT_PATH env or platform default).",
    )
    cmp_p.add_argument(
        "--json", action="store_true",
        help="Emit full comparison as JSON on stdout.",
    )
    cmp_p.add_argument(
        "--tolerance-config", type=Path, default=None,
        help=(
            "Path to .diffmeta.yaml with per-measure/method/field "
            "tolerances. Defaults to autodiscovery of `.diffmeta.yaml` "
            "in CWD."
        ),
    )

    args = parser.parse_args(argv)

    if args.cmd == "compare":
        # Resolve tolerance config: explicit path, then autodiscover in
        # CWD, else None (falls back to legacy built-in multipliers).
        tol_cfg: Optional[ToleranceConfig] = None
        if args.tolerance_config is not None:
            tol_cfg = ToleranceConfig.from_yaml(args.tolerance_config)
        elif Path(".diffmeta.yaml").is_file():
            tol_cfg = ToleranceConfig.from_yaml(".diffmeta.yaml")

        try:
            result = compare(
                args.csv,
                measure=args.measure, method=args.method,
                tolerance=args.tolerance, rscript_path=args.rscript,
                tolerance_config=tol_cfg,
            )
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            print(f"diffmeta error: {e}", file=sys.stderr)
            return 2

        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            p = result.python
            r = result.r
            print(f"measure={result.measure}  method={result.method}  k={p.k}")
            print(f"Python:  estimate = {p.estimate:+.10f}  se = {p.se:.10f}  tau2 = {p.tau2:.6g}")
            print(f"R:       estimate = {r.estimate:+.10f}  se = {r.se:.10f}  tau2 = {r.tau2:.6g}")
            print(f"max abs diff: {result.max_abs_diff:.2e}  tolerance: {result.tolerance:.2e}")
            print("VERDICT:", "DIVERGES" if result.diverges else "AGREES")
            if result.diverges:
                for field_name, d in result.field_diffs.items():
                    marker = "!" if d > result.tolerance else " "
                    print(f"  {marker} {field_name}: {d:.2e}")
        return 1 if result.diverges else 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
