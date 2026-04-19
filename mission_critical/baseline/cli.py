"""baseline CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mission_critical.baseline.store import (
    DEFAULT_TOLERANCE,
    BaselineStore,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="baseline",
        description="Record and diff-check shipped MAs' numerical results.",
    )
    parser.add_argument(
        "--store", type=Path, default=Path("baseline.json"),
        help="Path to JSON store (default ./baseline.json).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    rec_p = sub.add_parser("record", help="Record a paper's baseline.")
    rec_p.add_argument("paper_id")
    rec_p.add_argument(
        "--from", dest="from_report", type=Path, default=None,
        help="Read numeric fields from a JSON report file (e.g. diffmeta output).",
    )
    rec_p.add_argument(
        "--commit", default=None, help="Commit SHA anchoring this baseline.",
    )
    rec_p.add_argument(
        "--overwrite", action="store_true",
        help="Replace an existing record for this paper_id.",
    )
    rec_p.add_argument(
        "--value", action="append", default=[], metavar="KEY=FLOAT",
        help="Set a numeric field directly. Repeatable.",
    )

    sub.add_parser("list", help="List recorded baselines.")

    diff_p = sub.add_parser(
        "diff",
        help="Compare a new report against the stored baseline; exit non-zero if over tolerance.",
    )
    diff_p.add_argument("paper_id")
    diff_p.add_argument(
        "--against", type=Path, required=True,
        help="JSON report file to compare against.",
    )
    diff_p.add_argument(
        "--tolerance", type=float, default=DEFAULT_TOLERANCE,
        help=f"Max allowed abs diff across numeric fields (default {DEFAULT_TOLERANCE:g}).",
    )

    args = parser.parse_args(argv)
    store = BaselineStore(args.store)

    if args.cmd == "record":
        kwargs: dict = {}
        for pair in args.value:
            if "=" not in pair:
                print(f"baseline error: expected KEY=FLOAT, got {pair!r}", file=sys.stderr)
                return 2
            k, _, v = pair.partition("=")
            try:
                kwargs[k.strip()] = float(v)
            except ValueError:
                print(f"baseline error: {v!r} is not a float", file=sys.stderr)
                return 2

        try:
            if args.from_report is not None:
                report = json.loads(args.from_report.read_text(encoding="utf-8"))
                rec = store.record_from_report(
                    args.paper_id, report,
                    commit_sha=args.commit, overwrite=args.overwrite,
                )
                for k, v in kwargs.items():
                    # Merge CLI --value overrides on top of report
                    if hasattr(rec, k):
                        setattr(rec, k, v)
                    else:
                        rec.extra[k] = v
            else:
                rec = store.record(
                    args.paper_id, commit_sha=args.commit,
                    overwrite=args.overwrite, **kwargs,
                )
        except (OSError, KeyError, json.JSONDecodeError) as e:
            print(f"baseline error: {e}", file=sys.stderr)
            return 2

        store.save()
        fields = rec.numeric_fields()
        print(f"recorded {rec.paper_id}: {len(fields)} numeric field(s) at {rec.recorded_at}")
        for k, v in sorted(fields.items()):
            print(f"  {k} = {v}")
        return 0

    if args.cmd == "list":
        records = store.all()
        if not records:
            print("(empty)")
            return 0
        for r in records:
            n = len(r.numeric_fields())
            print(f"  {r.paper_id}  recorded_at={r.recorded_at}  fields={n}")
        return 0

    if args.cmd == "diff":
        try:
            report = json.loads(args.against.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"baseline error: {e}", file=sys.stderr)
            return 2

        # Accept either a flat numeric-fields dict, or a nested diffmeta report.
        src = report.get("pooled") or report.get("python") or report
        # Rename diffmeta's log_or to pooled_estimate for baseline match
        if "log_or" in src and "pooled_estimate" not in src:
            src = dict(src)
            src["pooled_estimate"] = src.pop("log_or")
        numeric = {
            k: float(v) for k, v in src.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }

        try:
            rpt = store.diff(
                args.paper_id, numeric, tolerance=args.tolerance,
            )
        except KeyError as e:
            print(f"baseline error: {e}", file=sys.stderr)
            return 2

        print(f"paper: {rpt.paper_id}")
        print(f"tolerance: {rpt.tolerance:.2e}  max_abs_diff: {rpt.max_abs_diff:.2e}")
        if not rpt.diffs:
            print("VERDICT: MATCHES")
            return 0
        print("diffs:")
        for field_name, (old, new, d) in sorted(rpt.diffs.items()):
            marker = "!" if d > rpt.tolerance else " "
            print(f"  {marker} {field_name}: {old} -> {new}  (|Δ| = {d:.2e})")
        print("VERDICT:", "EXCEEDS" if rpt.exceeds_tolerance else "WITHIN")
        return 1 if rpt.exceeds_tolerance else 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
