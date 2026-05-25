"""Tests for numerical baseline corpus."""
from __future__ import annotations

from pathlib import Path

import pytest
from mission_critical.baseline.store import (
    BaselineRecord,
    BaselineStore,
)


def test_record_and_retrieve(tmp_path: Path):
    store = BaselineStore(tmp_path / "b.json")
    store.record(
        "paradigm-hf-2014",
        pooled_estimate=-0.223,
        ci_lower=-0.311,
        ci_upper=-0.135,
        i2=0.0,
        k=8442,
        commit_sha="abc1234",
    )
    store.save()

    store2 = BaselineStore(tmp_path / "b.json")
    r = store2.get("paradigm-hf-2014")
    assert r is not None
    assert r.pooled_estimate == pytest.approx(-0.223)
    assert r.k == 8442


def test_record_rejects_duplicate_without_overwrite(tmp_path: Path):
    store = BaselineStore(tmp_path / "b.json")
    store.record("p1", pooled_estimate=1.0)
    with pytest.raises(KeyError):
        store.record("p1", pooled_estimate=2.0)


def test_record_allows_overwrite(tmp_path: Path):
    store = BaselineStore(tmp_path / "b.json")
    store.record("p1", pooled_estimate=1.0)
    store.record("p1", pooled_estimate=2.0, overwrite=True)
    assert store.get("p1").pooled_estimate == 2.0


def test_diff_matches_within_tolerance(tmp_path: Path):
    store = BaselineStore(tmp_path / "b.json")
    store.record(
        "p1",
        pooled_estimate=-0.223456789,
        ci_lower=-0.311,
        ci_upper=-0.135,
    )
    report = store.diff("p1", {
        "pooled_estimate": -0.223456789,
        "ci_lower": -0.311,
        "ci_upper": -0.135,
    })
    assert report.exceeds_tolerance is False
    assert report.max_abs_diff == 0.0
    assert report.diffs == {}


def test_diff_flags_drift_beyond_tolerance(tmp_path: Path):
    """Classic incident: HR shifted from 0.80 to 0.81 after adding
    studies. Must trigger at default 1e-6 tolerance."""
    store = BaselineStore(tmp_path / "b.json")
    store.record("sglt2i-hfpef", pooled_estimate=0.80)
    report = store.diff("sglt2i-hfpef", {"pooled_estimate": 0.81})
    assert report.exceeds_tolerance is True
    assert "pooled_estimate" in report.diffs
    old, new, d = report.diffs["pooled_estimate"]
    assert old == 0.80
    assert new == 0.81
    assert d == pytest.approx(0.01)


def test_diff_noise_under_tolerance_passes(tmp_path: Path):
    """Floating-point noise below tolerance must not trigger."""
    store = BaselineStore(tmp_path / "b.json")
    store.record("p1", pooled_estimate=0.80)
    report = store.diff(
        "p1",
        {"pooled_estimate": 0.80 + 1e-10},
        tolerance=1e-6,
    )
    assert report.exceeds_tolerance is False
    assert report.max_abs_diff == pytest.approx(1e-10, rel=1e-3)


def test_diff_unknown_paper_raises(tmp_path: Path):
    store = BaselineStore(tmp_path / "b.json")
    with pytest.raises(KeyError, match="No baseline recorded"):
        store.diff("never-recorded", {"pooled_estimate": 1.0})


def test_record_from_report_consumes_diffmeta_output(tmp_path: Path):
    """baseline record --from should accept a diffmeta JSON report
    without manual reshaping."""
    store = BaselineStore(tmp_path / "b.json")
    report = {
        "python": {
            "log_or": -0.223,
            "se": 0.044,
            "ci_lower": -0.311,
            "ci_upper": -0.135,
            "q": 2.4,
            "k": 5,
        },
        "r": {
            "log_or": -0.223,
            "se": 0.044,
            "ci_lower": -0.311,
            "ci_upper": -0.135,
            "q": 2.4,
            "k": 5,
        },
        "diverges": False,
    }
    rec = store.record_from_report("p1", report)
    # log_or in diffmeta becomes pooled_estimate in baseline
    assert rec.pooled_estimate == pytest.approx(-0.223)
    assert rec.se == pytest.approx(0.044)
    assert rec.k == 5


def test_extra_fields_roundtrip(tmp_path: Path):
    store = BaselineStore(tmp_path / "b.json")
    store.record(
        "p1",
        pooled_estimate=1.0,
        sucra=0.87,  # extra
        fragility_index=3,  # extra
    )
    store.save()
    store2 = BaselineStore(tmp_path / "b.json")
    r = store2.get("p1")
    assert r.extra["sucra"] == pytest.approx(0.87)
    assert r.extra["fragility_index"] == pytest.approx(3.0)


def test_numeric_fields_flattens_extras(tmp_path: Path):
    rec = BaselineRecord(
        paper_id="p1",
        recorded_at="2026-04-19T00:00:00Z",
        commit_sha=None,
        pooled_estimate=1.0,
        extra={"sucra": 0.87},
    )
    fields = rec.numeric_fields()
    assert fields["pooled_estimate"] == 1.0
    assert fields["extra.sucra"] == pytest.approx(0.87)
    # None-valued fields must not leak
    assert "ci_lower" not in fields


def test_malformed_json_raises(tmp_path: Path):
    p = tmp_path / "b.json"
    p.write_text("not valid json{", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Cannot read baseline store"):
        BaselineStore(p)
