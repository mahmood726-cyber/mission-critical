"""Tests for RO-Crate 1.2 export of baseline + provenance."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mission_critical.baseline.rocrate import build_crate
from mission_critical.baseline.store import BaselineStore


def _rocrate_available() -> bool:
    try:
        import rocrate  # noqa: F401
        return True
    except ImportError:
        return False


_HAS_ROCRATE = _rocrate_available()


@pytest.mark.skipif(not _HAS_ROCRATE, reason="rocrate-py not installed")
def test_build_crate_writes_metadata(tmp_path: Path):
    # Seed a baseline
    store = BaselineStore(tmp_path / "baseline.json")
    store.record("paper-1", pooled_estimate=1.0)
    store.save()

    out_dir = tmp_path / "crate"
    result = build_crate(tmp_path / "baseline.json", out_dir)
    assert result == out_dir
    assert (out_dir / "ro-crate-metadata.json").is_file()
    assert (out_dir / "baseline.json").is_file()


@pytest.mark.skipif(not _HAS_ROCRATE, reason="rocrate-py not installed")
def test_build_crate_includes_provenance_when_supplied(tmp_path: Path):
    store = BaselineStore(tmp_path / "baseline.json")
    store.record("paper-1", pooled_estimate=1.0)
    store.save()
    (tmp_path / "provenance.json").write_text(
        '{"schema_version":"0.1","entries":{}}', encoding="utf-8",
    )

    out_dir = tmp_path / "crate"
    build_crate(
        tmp_path / "baseline.json", out_dir,
        provenance_path=tmp_path / "provenance.json",
    )
    assert (out_dir / "provenance.json").is_file()


@pytest.mark.skipif(not _HAS_ROCRATE, reason="rocrate-py not installed")
def test_build_crate_includes_report_files(tmp_path: Path):
    store = BaselineStore(tmp_path / "baseline.json")
    store.record("paper-1", pooled_estimate=1.0)
    store.save()
    report = tmp_path / "paper-1.report.json"
    report.write_text('{"pooled_estimate":1.0}', encoding="utf-8")

    out_dir = tmp_path / "crate"
    build_crate(
        tmp_path / "baseline.json", out_dir, report_paths=[report],
    )
    assert (out_dir / "paper-1.report.json").is_file()


@pytest.mark.skipif(not _HAS_ROCRATE, reason="rocrate-py not installed")
def test_crate_metadata_references_baseline_file(tmp_path: Path):
    store = BaselineStore(tmp_path / "baseline.json")
    store.record("paper-1", pooled_estimate=1.0)
    store.save()

    out_dir = tmp_path / "crate"
    build_crate(tmp_path / "baseline.json", out_dir)

    metadata = json.loads(
        (out_dir / "ro-crate-metadata.json").read_text(encoding="utf-8")
    )
    # RO-Crate metadata contains @graph with file entries
    assert "@graph" in metadata
    file_ids = [node.get("@id") for node in metadata["@graph"]
                if isinstance(node, dict)]
    assert "baseline.json" in file_ids


def test_build_crate_raises_when_rocrate_missing(tmp_path: Path, monkeypatch):
    """If rocrate-py is unavailable, build_crate raises a clear error."""
    from mission_critical.baseline import rocrate as mod
    monkeypatch.setattr(mod, "_HAS_ROCRATE", False)

    store = BaselineStore(tmp_path / "baseline.json")
    store.record("paper-1", pooled_estimate=1.0)
    store.save()

    with pytest.raises(RuntimeError, match="rocrate-py not installed"):
        build_crate(tmp_path / "baseline.json", tmp_path / "crate")
