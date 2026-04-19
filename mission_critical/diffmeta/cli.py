"""diffmeta CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mission_critical.diffmeta.engine import (
    DEFAULT_TOLERANCE,
    compare_binary_or,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="diffmeta",
        description="Differential-engine meta-analysis verifier (Python vs R metafor).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    cmp_p = sub.add_parser(
        "compare",
        help="Run both engines on a 2x2 CSV; exit non-zero on divergence.",
    )
    cmp_p.add_argument("csv", type=Path, help="CSV with columns ai, bi, ci, di.")
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

    args = parser.parse_args(argv)

    if args.cmd == "compare":
        try:
            result = compare_binary_or(
                args.csv, tolerance=args.tolerance, rscript_path=args.rscript,
            )
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            print(f"diffmeta error: {e}", file=sys.stderr)
            return 2

        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(f"k = {result.python.k} studies")
            print(f"Python:  log_or = {result.python.log_or:+.10f}  se = {result.python.se:.10f}")
            print(f"R:       log_or = {result.r.log_or:+.10f}  se = {result.r.se:.10f}")
            print(f"max abs diff: {result.max_abs_diff:.2e}  tolerance: {result.tolerance:.2e}")
            print("VERDICT:", "DIVERGES" if result.diverges else "AGREES")
            if result.diverges:
                for field, d in result.field_diffs.items():
                    marker = "!" if d > result.tolerance else " "
                    print(f"  {marker} {field}: {d:.2e}")
        return 1 if result.diverges else 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
