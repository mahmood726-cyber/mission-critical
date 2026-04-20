"""YAML-driven tolerance registry (ESMValTool-style, applied to diffmeta).

Let a project override the hardcoded default tolerances per-field,
per-measure, per-method. Replaces what used to be hardcoded in
`diffmeta.engine._FIELD_TOLERANCE_MULTIPLIERS_RE`.

Example `.diffmeta.yaml` at a paper's repo root:

    base_tolerance: 1.0e-6

    # Per-method override (multiplier on base)
    methods:
      FE:   {}                         # strict
      DL:   {}                         # strict
      REML:
        se: 10
        ci_lower: 10
        ci_upper: 10
        z_or_t: 10
        tau2: 100
        i2: 10000
      HKSJ:
        se: 10
        ci_lower: 10
        ci_upper: 10
        z_or_t: 10
        tau2: 100
        i2: 10000

    # Per-measure override (rare; lets SMD accept looser tau2)
    measures:
      SMD:
        tau2: 1000

Field precedence: measure override > method override > base.
Falls back to the built-in _DEFAULT_MULTIPLIERS when no config present.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml  # type: ignore[import-untyped]
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


DEFAULT_BASE_TOLERANCE = 1.0e-6

# Sensible defaults matching what was previously hardcoded in diffmeta.engine.
_DEFAULT_MULTIPLIERS: dict[str, dict[str, float]] = {
    "FE": {},
    "DL": {},
    "REML": {
        "se": 10.0,
        "ci_lower": 10.0,
        "ci_upper": 10.0,
        "z_or_t": 10.0,
        "tau2": 100.0,
        "i2": 1.0e4,
    },
    "HKSJ": {
        "se": 10.0,
        "ci_lower": 10.0,
        "ci_upper": 10.0,
        "z_or_t": 10.0,
        "tau2": 100.0,
        "i2": 1.0e4,
    },
}


@dataclass
class ToleranceConfig:
    """Resolved tolerance lookup for (measure, method, field)."""
    base_tolerance: float = DEFAULT_BASE_TOLERANCE
    method_multipliers: dict[str, dict[str, float]] = field(default_factory=dict)
    measure_multipliers: dict[str, dict[str, float]] = field(default_factory=dict)

    def tolerance_for(
        self, field_name: str, measure: str, method: str,
    ) -> float:
        # Measure-specific > method-specific > default-method > 1.0
        mults = self.measure_multipliers.get(measure, {})
        if field_name in mults:
            return self.base_tolerance * mults[field_name]
        mults = self.method_multipliers.get(method, {})
        if field_name in mults:
            return self.base_tolerance * mults[field_name]
        default_mults = _DEFAULT_MULTIPLIERS.get(method, {})
        if field_name in default_mults:
            return self.base_tolerance * default_mults[field_name]
        return self.base_tolerance

    @classmethod
    def default(cls) -> "ToleranceConfig":
        return cls()

    @classmethod
    def from_yaml(cls, path: Path | str) -> "ToleranceConfig":
        if not _HAS_YAML:
            raise RuntimeError(
                "PyYAML required to load .diffmeta.yaml (pip install pyyaml)"
            )
        path = Path(path)
        try:
            data = _yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, _yaml.YAMLError) as e:
            raise RuntimeError(f"cannot read {path}: {e}") from e
        if data is None:
            return cls.default()
        if not isinstance(data, dict):
            raise RuntimeError(f"{path}: top-level YAML must be a mapping")
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "ToleranceConfig":
        base = float(data.get("base_tolerance", DEFAULT_BASE_TOLERANCE))
        method_mults: dict[str, dict[str, float]] = {}
        for method, overrides in (data.get("methods") or {}).items():
            if isinstance(overrides, dict):
                method_mults[str(method)] = {
                    str(k): float(v) for k, v in overrides.items()
                    if v is not None
                }
        measure_mults: dict[str, dict[str, float]] = {}
        for measure, overrides in (data.get("measures") or {}).items():
            if isinstance(overrides, dict):
                measure_mults[str(measure)] = {
                    str(k): float(v) for k, v in overrides.items()
                    if v is not None
                }
        return cls(
            base_tolerance=base,
            method_multipliers=method_mults,
            measure_multipliers=measure_mults,
        )

    @classmethod
    def from_repo(cls, repo_root: Path | str) -> "ToleranceConfig":
        """Look for `.diffmeta.yaml` at repo root; return default if missing."""
        path = Path(repo_root) / ".diffmeta.yaml"
        if not path.is_file():
            return cls.default()
        return cls.from_yaml(path)
