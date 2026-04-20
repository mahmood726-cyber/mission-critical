"""JSON-backed numerical baseline corpus."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_TOLERANCE = 1e-6


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_claim_id() -> str:
    """Generate a persistent, URL-safe claim ID (HEPData-style).

    Short form: `cl_<8 hex>` — 32 bits of entropy, collision probability
    negligible for a single researcher's corpus. Survives paper_id renames,
    title changes, path moves. The ID, not the paper_id, is the stable
    reference for citations and cross-repo references.
    """
    return "cl_" + uuid.uuid4().hex[:8]


@dataclass
class BaselineRecord:
    """One paper's shipped numerical results."""
    paper_id: str
    recorded_at: str
    commit_sha: str | None
    # Canonical numerical fields (all optional — a paper may report
    # some but not others). Values are plain floats.
    pooled_estimate: float | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    se: float | None = None
    i2: float | None = None
    tau2: float | None = None
    q: float | None = None
    k: int | None = None
    # Catch-all for additional numeric fields a paper might track
    # (e.g. SUCRA for NMA, fragility index, prediction interval
    # bounds). Keys must be strings; values must be numeric.
    extra: dict[str, float] = field(default_factory=dict)
    # Persistent claim ID (HEPData pattern). Auto-assigned on new
    # records. Outlives paper_id renames, so a paper cited as cl_abcd1234
    # remains traceable even if the paper_id changes from
    # "sglt2i-hfpef-v1.0" to "sglt2i-hfpef-v1.1".
    claim_id: str = field(default_factory=_new_claim_id)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BaselineRecord":
        # Filter unknown keys so old or future schemas don't crash.
        # A pre-claim_id record on disk won't have `claim_id`; the
        # default factory will mint one on load (one-shot migration).
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)

    def numeric_fields(self) -> dict[str, float]:
        """All numeric fields flattened for diff comparison."""
        out: dict[str, float] = {}
        for name in ("pooled_estimate", "ci_lower", "ci_upper", "se",
                     "i2", "tau2", "q"):
            v = getattr(self, name)
            if v is not None:
                out[name] = float(v)
        if self.k is not None:
            out["k"] = float(self.k)
        for key, val in self.extra.items():
            if val is None:
                continue
            out[f"extra.{key}"] = float(val)
        return out


@dataclass
class DiffReport:
    paper_id: str
    tolerance: float
    baseline_fields: dict[str, float]
    new_fields: dict[str, float]
    diffs: dict[str, tuple[float, float, float]]  # field -> (old, new, abs_diff)
    max_abs_diff: float
    exceeds_tolerance: bool

    def to_dict(self) -> dict:
        return {
            "paper_id": self.paper_id,
            "tolerance": self.tolerance,
            "baseline_fields": self.baseline_fields,
            "new_fields": self.new_fields,
            "diffs": {k: list(v) for k, v in self.diffs.items()},
            "max_abs_diff": self.max_abs_diff,
            "exceeds_tolerance": self.exceeds_tolerance,
        }


class BaselineStore:
    """JSON file on disk, one paper per record."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._records: dict[str, BaselineRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise RuntimeError(
                f"Cannot read baseline store at {self.path}: {e}"
            ) from e
        for paper_id, data in raw.get("records", {}).items():
            self._records[paper_id] = BaselineRecord.from_dict(data)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "0.1",
            "records": {
                pid: r.to_dict() for pid, r in sorted(self._records.items())
            },
        }
        self.path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

    def record(
        self,
        paper_id: str,
        *,
        commit_sha: str | None = None,
        overwrite: bool = False,
        claim_id: str | None = None,
        **numeric_fields: Any,
    ) -> BaselineRecord:
        if paper_id in self._records and not overwrite:
            raise KeyError(
                f"Paper {paper_id!r} already recorded. Use overwrite=True to replace."
            )
        # On overwrite, preserve the existing claim_id so the stable
        # reference survives paper_id rename or re-record. On first record,
        # take an explicitly-supplied claim_id or let the dataclass default
        # factory assign a fresh one.
        if overwrite and paper_id in self._records and claim_id is None:
            claim_id = self._records[paper_id].claim_id

        known = {
            "pooled_estimate", "ci_lower", "ci_upper", "se",
            "i2", "tau2", "q", "k",
        }
        kwargs = {k: v for k, v in numeric_fields.items() if k in known}
        extra = {
            k: float(v) for k, v in numeric_fields.items()
            if k not in known and v is not None
        }
        ctor_kwargs: dict[str, Any] = dict(
            paper_id=paper_id,
            recorded_at=_utc_now(),
            commit_sha=commit_sha,
            extra=extra,
            **kwargs,
        )
        if claim_id is not None:
            ctor_kwargs["claim_id"] = claim_id
        rec = BaselineRecord(**ctor_kwargs)
        self._records[paper_id] = rec
        return rec

    def record_from_report(
        self,
        paper_id: str,
        report: dict,
        *,
        commit_sha: str | None = None,
        overwrite: bool = False,
    ) -> BaselineRecord:
        """Record from a dict produced by e.g. diffmeta compare --json."""
        # diffmeta's Python/R output structure: {"python": {...}, "r": {...}, ...}
        # Prefer an explicit "pooled" block if present; else fall back to "python".
        src = report.get("pooled") or report.get("python") or report
        return self.record(
            paper_id,
            commit_sha=commit_sha,
            overwrite=overwrite,
            pooled_estimate=src.get("log_or") or src.get("pooled_estimate"),
            ci_lower=src.get("ci_lower"),
            ci_upper=src.get("ci_upper"),
            se=src.get("se"),
            i2=src.get("i2"),
            tau2=src.get("tau2"),
            q=src.get("q"),
            k=src.get("k"),
        )

    def get(self, paper_id: str) -> BaselineRecord | None:
        return self._records.get(paper_id)

    def all(self) -> list[BaselineRecord]:
        return sorted(self._records.values(), key=lambda r: r.paper_id)

    def diff(
        self,
        paper_id: str,
        new_fields: dict[str, float],
        *,
        tolerance: float = DEFAULT_TOLERANCE,
    ) -> DiffReport:
        rec = self._records.get(paper_id)
        if rec is None:
            raise KeyError(f"No baseline recorded for paper {paper_id!r}")
        baseline = rec.numeric_fields()

        diffs: dict[str, tuple[float, float, float]] = {}
        max_diff = 0.0
        for key, old_val in baseline.items():
            if key not in new_fields:
                continue
            new_val = float(new_fields[key])
            d = abs(new_val - old_val)
            if d > 0:
                diffs[key] = (old_val, new_val, d)
                if d > max_diff:
                    max_diff = d

        return DiffReport(
            paper_id=paper_id,
            tolerance=tolerance,
            baseline_fields=baseline,
            new_fields={k: float(v) for k, v in new_fields.items()},
            diffs=diffs,
            max_abs_diff=max_diff,
            exceeds_tolerance=max_diff > tolerance,
        )
