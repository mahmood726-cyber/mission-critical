"""JSON-backed provenance store for identifiers + extracted values."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NCT_RE = re.compile(r"^NCT\d{8}$")
PMID_RE = re.compile(r"^\d{1,9}$")
DOI_RE = re.compile(r"^10\.\d{4,9}/[^\s]+$")


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

    def unverified(self) -> list[ProvenanceEntry]:
        return [e for e in self._entries.values() if not e.verified]
