"""Tests for pytest-regressions interop adapter."""
from __future__ import annotations

from pathlib import Path

import pytest
from mission_critical.baseline.pytest_regressions_adapter import (
    export_to_pytest_regressions,
    import_from_pytest_regressions_yaml,
)
from mission_critical.baseline.store import BaselineStore


def _yaml_available() -> bool:
    try:
        import yaml  # noqa: F401
        return True
    except ImportError:
        return False


_HAS_YAML = _yaml_available()


@pytest.mark.skipif(not _HAS_YAML, reason="PyYAML not installed")
def test_export_writes_one_fixture_per_paper(tmp_path: Path):
    store = BaselineStore(tmp_path / "baseline.json")
    store.record("paradigm-hf", pooled_estimate=-0.223)
    store.record("sglt2i-hfpef", pooled_estimate=-0.214)
    store.save()

    out_dir = tmp_path / "fixtures"
    paths = export_to_pytest_regressions(store, out_dir)
    assert len(paths) == 2
    assert all(p.exists() for p in paths)
    names = sorted(p.name for p in paths)
    assert names == [
        "test_paradigm_hf_stable.yml",
        "test_sglt2i_hfpef_stable.yml",
    ]


@pytest.mark.skipif(not _HAS_YAML, reason="PyYAML not installed")
def test_exported_yaml_has_numeric_fields(tmp_path: Path):
    import yaml
    store = BaselineStore(tmp_path / "baseline.json")
    store.record(
        "paper-1",
        pooled_estimate=-0.223, ci_lower=-0.311, ci_upper=-0.135,
    )
    store.save()
    paths = export_to_pytest_regressions(store, tmp_path / "out")
    data = yaml.safe_load(paths[0].read_text(encoding="utf-8"))
    assert data["pooled_estimate"] == -0.223
    assert data["ci_lower"] == -0.311
    assert data["ci_upper"] == -0.135


@pytest.mark.skipif(not _HAS_YAML, reason="PyYAML not installed")
def test_roundtrip_preserves_values(tmp_path: Path):
    # Seed
    store = BaselineStore(tmp_path / "baseline.json")
    store.record("paper-1", pooled_estimate=0.8069, ci_lower=0.7395)
    store.save()

    # Export to pytest-regressions fixtures
    export_to_pytest_regressions(store, tmp_path / "fixtures")

    # Fresh store, import from those fixtures
    store2 = BaselineStore(tmp_path / "baseline2.json")
    records = import_from_pytest_regressions_yaml(
        store2, tmp_path / "fixtures",
    )
    assert len(records) == 1
    rec = store2.get("paper-1")
    assert rec is not None
    assert rec.pooled_estimate == pytest.approx(0.8069)
    assert rec.ci_lower == pytest.approx(0.7395)


@pytest.mark.skipif(not _HAS_YAML, reason="PyYAML not installed")
def test_export_preserves_commit_sha_in_comment(tmp_path: Path):
    store = BaselineStore(tmp_path / "baseline.json")
    store.record(
        "paper-1", pooled_estimate=1.0, commit_sha="abc12345",
    )
    store.save()
    paths = export_to_pytest_regressions(store, tmp_path / "out")
    text = paths[0].read_text(encoding="utf-8")
    assert "commit_sha: abc12345" in text
