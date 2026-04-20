"""provenance CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mission_critical.provenance.store import ProvenanceStore


def _parse_kv(pairs: list[str]) -> dict:
    out: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Expected key=value, got: {pair!r}")
        key, _, val = pair.partition("=")
        key = key.strip()
        val = val.strip()
        # try int then float then leave as string
        try:
            out[key] = int(val)
            continue
        except ValueError:
            pass
        try:
            out[key] = float(val)
            continue
        except ValueError:
            pass
        out[key] = val
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="provenance",
        description="Record and verify identifier + data-extraction provenance.",
    )
    parser.add_argument(
        "--store", type=Path, default=Path("provenance.json"),
        help="Path to JSON store (default ./provenance.json).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    add_p = sub.add_parser("add", help="Add a new identifier entry.")
    add_p.add_argument("identifier", help="e.g. NCT00095238 or 10.1056/NEJMoa1409077")
    add_p.add_argument("--source", required=True, help='Extraction source (e.g. "paper.pdf:p12").')
    add_p.add_argument("--extractor", default="human", help="human / tool-name.")
    add_p.add_argument("--commit", default=None, help="Commit SHA anchoring extraction.")
    add_p.add_argument(
        "--value", action="append", default=[], metavar="KEY=VALUE",
        help="Extracted value (repeatable). e.g. --value N=5050 --value HR=0.80",
    )
    add_p.add_argument("--verified", action="store_true", help="Mark as human-verified.")

    sub.add_parser("list", help="List all entries.")

    ver_p = sub.add_parser("verify", help="Mark an entry as human-verified.")
    ver_p.add_argument("identifier")
    ver_p.add_argument("--commit", default=None)

    diff_p = sub.add_parser(
        "diff",
        help="Compare new values against the stored entry; exit non-zero on diff.",
    )
    diff_p.add_argument("identifier")
    diff_p.add_argument(
        "--value", action="append", default=[], metavar="KEY=VALUE",
        required=True,
    )

    unv_p = sub.add_parser("unverified", help="List entries that aren't human-verified.")
    unv_p.add_argument("--fail", action="store_true", help="Exit 1 if any unverified.")

    exp_p = sub.add_parser(
        "export",
        help="Export the provenance store to another format.",
    )
    exp_sub = exp_p.add_subparsers(dest="export_fmt", required=True)
    prov_p = exp_sub.add_parser(
        "prov-o",
        help="Emit W3C PROV-O JSON-LD for interop with Whole Tale / RO-Crate / ELN.",
    )
    prov_p.add_argument("out_path", type=Path)

    args = parser.parse_args(argv)
    store = ProvenanceStore(args.store)

    if args.cmd == "add":
        try:
            values = _parse_kv(args.value)
        except ValueError as e:
            print(f"provenance error: {e}", file=sys.stderr)
            return 2
        try:
            entry = store.add(
                args.identifier,
                source=args.source,
                extractor=args.extractor,
                values=values,
                verified=args.verified,
                commit_sha=args.commit,
            )
        except KeyError as e:
            print(f"provenance error: {e}", file=sys.stderr)
            return 2
        store.save()
        print(f"added {entry.kind} {entry.identifier} "
              f"(verified={entry.verified}, values={len(entry.values)})")
        return 0

    if args.cmd == "list":
        entries = store.all()
        if not entries:
            print("(empty)")
            return 0
        for e in entries:
            flag = "OK " if e.verified else "?? "
            print(f"  {flag} {e.kind:5s} {e.identifier}  "
                  f"source={e.source}  values={len(e.values)}")
        return 0

    if args.cmd == "verify":
        try:
            entry = store.mark_verified(args.identifier, commit_sha=args.commit)
        except KeyError as e:
            print(f"provenance error: {e}", file=sys.stderr)
            return 2
        store.save()
        print(f"verified {entry.identifier} at {entry.verified_at}")
        return 0

    if args.cmd == "diff":
        try:
            new_vals = _parse_kv(args.value)
        except ValueError as e:
            print(f"provenance error: {e}", file=sys.stderr)
            return 2
        try:
            diffs = store.diff_values(args.identifier, new_vals)
        except KeyError as e:
            print(f"provenance error: {e}", file=sys.stderr)
            return 2
        if not diffs:
            print("no differences")
            return 0
        print(f"DIFFS for {args.identifier}:")
        for key, (old, new) in diffs.items():
            print(f"  {key}: {old!r} -> {new!r}")
        return 1

    if args.cmd == "unverified":
        entries = store.unverified()
        if not entries:
            print("(all entries verified)")
            return 0
        for e in entries:
            print(f"  ?? {e.kind:5s} {e.identifier}  source={e.source}")
        if args.fail:
            return 1
        return 0

    if args.cmd == "export":
        if args.export_fmt == "prov-o":
            from mission_critical.provenance.prov import write_prov_o
            try:
                out = write_prov_o(store, args.out_path)
            except (OSError, RuntimeError) as e:
                print(f"provenance error: {e}", file=sys.stderr)
                return 2
            print(f"wrote PROV-O JSON-LD to {out}")
            return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
