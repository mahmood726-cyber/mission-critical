"""Tests for the YAML tolerance registry."""
from __future__ import annotations

from pathlib import Path

import pytest

from mission_critical.tolerance_config import (
    DEFAULT_BASE_TOLERANCE,
    ToleranceConfig,
)


def test_default_returns_base_for_unknown_field():
    cfg = ToleranceConfig.default()
    assert cfg.tolerance_for("unknown_field", "OR", "FE") == DEFAULT_BASE_TOLERANCE


def test_default_matches_hardcoded_re_multipliers():
    """Defaults must preserve what was hardcoded in diffmeta.engine."""
    cfg = ToleranceConfig.default()
    # REML: se -> 10x, tau2 -> 100x, i2 -> 1e4x
    assert cfg.tolerance_for("se", "OR", "REML") == 10 * DEFAULT_BASE_TOLERANCE
    assert cfg.tolerance_for("tau2", "OR", "REML") == 100 * DEFAULT_BASE_TOLERANCE
    assert cfg.tolerance_for("i2", "OR", "REML") == 1e4 * DEFAULT_BASE_TOLERANCE
    # FE: all fields strict (no multiplier override)
    assert cfg.tolerance_for("se", "OR", "FE") == DEFAULT_BASE_TOLERANCE
    assert cfg.tolerance_for("tau2", "OR", "FE") == DEFAULT_BASE_TOLERANCE


def test_from_yaml_applies_method_override(tmp_path: Path):
    yaml_path = tmp_path / ".diffmeta.yaml"
    yaml_path.write_text(
        "base_tolerance: 1.0e-5\n"
        "methods:\n"
        "  REML:\n"
        "    se: 5\n"
        "    tau2: 50\n",
        encoding="utf-8",
    )
    cfg = ToleranceConfig.from_yaml(yaml_path)
    assert cfg.base_tolerance == 1e-5
    assert cfg.tolerance_for("se", "OR", "REML") == 5 * 1e-5
    assert cfg.tolerance_for("tau2", "OR", "REML") == 50 * 1e-5
    # Field not in config falls back to builtin default for that method
    # (at the new base scale): i2 has default multiplier 1e4 for REML.
    assert cfg.tolerance_for("i2", "OR", "REML") == 1e4 * 1e-5


def test_measure_override_beats_method(tmp_path: Path):
    """measures: SMD.tau2 override takes precedence over methods: REML.tau2."""
    yaml_path = tmp_path / ".diffmeta.yaml"
    yaml_path.write_text(
        "methods:\n"
        "  REML:\n"
        "    tau2: 100\n"
        "measures:\n"
        "  SMD:\n"
        "    tau2: 1000\n",
        encoding="utf-8",
    )
    cfg = ToleranceConfig.from_yaml(yaml_path)
    # SMD + REML: measure override wins
    assert cfg.tolerance_for("tau2", "SMD", "REML") == 1000 * DEFAULT_BASE_TOLERANCE
    # OR + REML: measure override doesn't apply; method override applies
    assert cfg.tolerance_for("tau2", "OR", "REML") == 100 * DEFAULT_BASE_TOLERANCE


def test_from_repo_missing_file_returns_default(tmp_path: Path):
    cfg = ToleranceConfig.from_repo(tmp_path)  # no .diffmeta.yaml
    assert cfg.base_tolerance == DEFAULT_BASE_TOLERANCE


def test_from_repo_reads_yaml_when_present(tmp_path: Path):
    (tmp_path / ".diffmeta.yaml").write_text(
        "base_tolerance: 2.5e-7\n", encoding="utf-8",
    )
    cfg = ToleranceConfig.from_repo(tmp_path)
    assert cfg.base_tolerance == 2.5e-7


def test_malformed_yaml_raises(tmp_path: Path):
    yaml_path = tmp_path / ".diffmeta.yaml"
    yaml_path.write_text("this is not: valid: yaml: [", encoding="utf-8")
    with pytest.raises(RuntimeError):
        ToleranceConfig.from_yaml(yaml_path)


def test_non_mapping_top_level_raises(tmp_path: Path):
    yaml_path = tmp_path / ".diffmeta.yaml"
    yaml_path.write_text("- just a list\n- of things\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="top-level YAML must be a mapping"):
        ToleranceConfig.from_yaml(yaml_path)
