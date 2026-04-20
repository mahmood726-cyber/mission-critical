"""JSON-backed provenance store for identifiers + extracted values."""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


NCT_RE = re.compile(r"^NCT\d{8}$")
PMID_RE = re.compile(r"^\d{1,9}$")
DOI_RE = re.compile(r"^10\.\d{4,9}/[^\s]+$")


# Drift classification — richer than raw diff_values tuples. See
# classify_diffs() below. "numeric_noise" is filtered out when
# float_tol is nonzero, so it never appears in emitted records.
ChangeClass = Literal["added", "null_transition", "type_changed", "value_changed"]


@dataclass(frozen=True)
class DriftRecord:
    key: str
    old_value: Any
    new_value: Any
    change_class: ChangeClass

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "change_class": self.change_class,
        }


def _is_numeric(value: Any) -> bool:
    """True for int or float, EXCLUDING bool (Python's isinstance quirk
    per lessons.md#python)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_nan(value: Any) -> bool:
    """True iff value is NaN. In extraction land NaN typically means
    'parse failed', which is semantically None — NOT a real data value.
    Review P2-4 (initial) + P2-R5 (generalize beyond Python float).

    Covers:
      - Python float NaN (`float('nan')`)
      - numpy.nan (IS a Python float at runtime)
      - Decimal('NaN') (separate type with its own .is_nan() method)
    """
    if isinstance(value, float):
        return math.isnan(value)
    # Decimal NaN doesn't inherit from float.
    try:
        from decimal import Decimal
        if isinstance(value, Decimal):
            return value.is_nan()
    except ImportError:  # pragma: no cover — decimal is stdlib
        pass
    return False


def _classify_change(old: Any, new: Any) -> ChangeClass:
    """Categorize a key's change given old and new are known to differ.

    Null transition wins over type change (semantically clearer: "we lost
    a value" is more actionable than "type changed to NoneType"). Numeric
    type flips (int↔float) are NOT type_changed — same semantic bucket.
    """
    if old is None or new is None:
        return "null_transition"
    old_numeric = _is_numeric(old)
    new_numeric = _is_numeric(new)
    if old_numeric != new_numeric:
        return "type_changed"
    if not old_numeric and type(old) is not type(new):
        return "type_changed"
    return "value_changed"


def _classify(identifier: str) -> str:
    if NCT_RE.match(identifier):
        return "NCT"
    if identifier.startswith("10.") and DOI_RE.match(identifier):
        return "DOI"
    if PMID_RE.match(identifier):
        return "PMID"
    return "other"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ProvenanceEntry:
    identifier: str
    kind: str
    source: str
    extractor: str
    extracted_at: str
    values: dict[str, Any] = field(default_factory=dict)
    verified: bool = False
    verified_at: str | None = None
    commit_sha: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ProvenanceEntry":
        return cls(**d)


class ProvenanceStore:
    """JSON file on disk, one identifier per entry."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._entries: dict[str, ProvenanceEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise RuntimeError(
                f"Cannot read provenance store at {self.path}: {e}"
            ) from e
        for ident, data in raw.get("entries", {}).items():
            self._entries[ident] = ProvenanceEntry.from_dict(data)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "0.1",
            "entries": {
                ident: e.to_dict() for ident, e in sorted(self._entries.items())
            },
        }
        self.path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

    def add(
        self,
        identifier: str,
        *,
        source: str,
        extractor: str,
        values: dict[str, Any] | None = None,
        verified: bool = False,
        commit_sha: str | None = None,
    ) -> ProvenanceEntry:
        if identifier in self._entries:
            raise KeyError(
                f"Identifier already exists: {identifier!r}. "
                "Use update() or delete first."
            )
        now = _utc_now()
        entry = ProvenanceEntry(
            identifier=identifier,
            kind=_classify(identifier),
            source=source,
            extractor=extractor,
            extracted_at=now,
            values=dict(values or {}),
            verified=verified,
            verified_at=now if verified else None,
            commit_sha=commit_sha,
        )
        self._entries[identifier] = entry
        return entry

    def get(self, identifier: str) -> ProvenanceEntry | None:
        return self._entries.get(identifier)

    def all(self) -> list[ProvenanceEntry]:
        return sorted(self._entries.values(), key=lambda e: e.identifier)

    def mark_verified(
        self, identifier: str, commit_sha: str | None = None,
    ) -> ProvenanceEntry:
        entry = self._entries.get(identifier)
        if entry is None:
            raise KeyError(f"Unknown identifier: {identifier!r}")
        entry.verified = True
        entry.verified_at = _utc_now()
        if commit_sha is not None:
            entry.commit_sha = commit_sha
        return entry

    def diff_values(
        self, identifier: str, new_values: dict[str, Any],
    ) -> dict[str, tuple[Any, Any]]:
        """Compare new_values against stored values; return changed keys.

        Returns {key: (old_value, new_value)} for each differing or
        newly-added key. Keys missing from new_values (but present in
        stored) are NOT flagged — the assumption is you re-extract a
        subset each time.
        """
        entry = self._entries.get(identifier)
        if entry is None:
            raise KeyError(f"Unknown identifier: {identifier!r}")
        diffs: dict[str, tuple[Any, Any]] = {}
        for key, new_val in new_values.items():
            old_val = entry.values.get(key)
            if old_val != new_val:
                diffs[key] = (old_val, new_val)
        return diffs

    def classify_diffs(
        self,
        identifier: str,
        new_values: dict[str, Any],
        *,
        float_tol: float = 0.0,
    ) -> list[DriftRecord]:
        """Richer drift detector. Same match semantics as `diff_values`
        (missing-in-new keys are NOT flagged), but each emitted record
        carries a `change_class` and sub-threshold numeric drift is
        filtered out when `float_tol > 0`.

        Change classes emitted:
          - "added"           — key not present in stored entry
          - "null_transition" — old or new is None (extraction loss /
                                recovery)
          - "type_changed"    — type buckets differ (numeric vs
                                non-numeric, or different non-numeric
                                types). int↔float is NOT type_changed —
                                same numeric bucket.
          - "value_changed"   — different value, same type bucket, not
                                within float_tol

        Absorbs (returns no record for):
          - Exact equality
          - Both numeric and |old-new| <= float_tol
        """
        entry = self._entries.get(identifier)
        if entry is None:
            raise KeyError(f"Unknown identifier: {identifier!r}")
        records: list[DriftRecord] = []
        for key, new_val in new_values.items():
            if key not in entry.values:
                records.append(
                    DriftRecord(key, None, new_val, "added")
                )
                continue
            old_val = entry.values[key]
            # NaN canonicalization: treat NaN as semantically None. Both-NaN
            # absorbs silently; NaN on one side becomes null_transition via
            # _classify_change. Review P2-4.
            old_nan = _is_nan(old_val)
            new_nan = _is_nan(new_val)
            if old_nan and new_nan:
                continue
            if old_nan:
                old_val = None
            if new_nan:
                new_val = None
            if old_val == new_val:
                continue
            # Filter numeric noise BEFORE classification. If both sides
            # are numeric and within tolerance, emit nothing — the caller
            # has declared they don't care about sub-threshold drift.
            if (
                float_tol > 0
                and _is_numeric(old_val)
                and _is_numeric(new_val)
                and abs(old_val - new_val) <= float_tol
            ):
                continue
            # NOTE: nested dict / list drift is NOT drilled-into. old={"a":1}
            # vs new={"a":2} reports the whole dict as value_changed. Current
            # provenance scope is flat (N, HR, dates); re-evaluate if nested
            # structures enter the store. Review P2-5.
            records.append(
                DriftRecord(key, old_val, new_val, _classify_change(old_val, new_val))
            )
        return records

    def unverified(self) -> list[ProvenanceEntry]:
        return [e for e in self._entries.values() if not e.verified]
