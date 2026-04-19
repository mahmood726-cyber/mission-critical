"""Tests for provenance store."""
from __future__ import annotations

from pathlib import Path

import pytest

from mission_critical.provenance.store import (
    ProvenanceStore,
    _classify,
)


def test_classify_nct():
    assert _classify("NCT01234567") == "NCT"
    assert _classify("NCT00095238") == "NCT"


def test_classify_doi():
    assert _classify("10.1056/NEJMoa1409077") == "DOI"


def test_classify_pmid():
    assert _classify("25176015") == "PMID"


def test_classify_other():
    assert _classify("random string") == "other"


def test_add_and_retrieve(tmp_path: Path):
    store = ProvenanceStore(tmp_path / "p.json")
    e = store.add(
        "NCT00095238",
        source="paradigm-hf.pdf:p12",
        extractor="human",
        values={"N": 8442, "HR": 0.80},
        verified=True,
    )
    assert e.kind == "NCT"
    assert e.verified is True
    assert e.values == {"N": 8442, "HR": 0.80}
    store.save()

    store2 = ProvenanceStore(tmp_path / "p.json")
    e2 = store2.get("NCT00095238")
    assert e2 is not None
    assert e2.values == {"N": 8442, "HR": 0.80}
    assert e2.verified is True


def test_add_rejects_duplicate(tmp_path: Path):
    store = ProvenanceStore(tmp_path / "p.json")
    store.add("NCT00095238", source="a", extractor="human")
    with pytest.raises(KeyError):
        store.add("NCT00095238", source="b", extractor="human")


def test_diff_values_detects_change(tmp_path: Path):
    """Classic provenance check: we extracted N=8442 earlier; now a
    new extraction says N=1807. Must flag."""
    store = ProvenanceStore(tmp_path / "p.json")
    store.add(
        "NCT00095238",
        source="paradigm-hf.pdf:p12",
        extractor="human",
        values={"N": 8442, "HR": 0.80},
    )
    diffs = store.diff_values("NCT00095238", {"N": 1807, "HR": 0.80})
    assert diffs == {"N": (8442, 1807)}


def test_diff_values_empty_when_clean(tmp_path: Path):
    store = ProvenanceStore(tmp_path / "p.json")
    store.add(
        "NCT00095238", source="a", extractor="human",
        values={"N": 8442},
    )
    assert store.diff_values("NCT00095238", {"N": 8442}) == {}


def test_diff_values_flags_new_key(tmp_path: Path):
    store = ProvenanceStore(tmp_path / "p.json")
    store.add("NCT00095238", source="a", extractor="human", values={"N": 1})
    diffs = store.diff_values("NCT00095238", {"HR": 0.80})
    assert "HR" in diffs
    assert diffs["HR"] == (None, 0.80)


def test_mark_verified(tmp_path: Path):
    store = ProvenanceStore(tmp_path / "p.json")
    e = store.add("NCT00095238", source="a", extractor="tool")
    assert e.verified is False
    store.mark_verified("NCT00095238", commit_sha="abc1234")
    assert store.get("NCT00095238").verified is True
    assert store.get("NCT00095238").commit_sha == "abc1234"


def test_unverified_returns_only_unverified(tmp_path: Path):
    store = ProvenanceStore(tmp_path / "p.json")
    store.add("NCT00000001", source="a", extractor="tool")
    store.add("NCT00000002", source="b", extractor="human", verified=True)
    unv = store.unverified()
    assert len(unv) == 1
    assert unv[0].identifier == "NCT00000001"


def test_roundtrip_preserves_extracted_at(tmp_path: Path):
    """JSON roundtrip must not lose the UTC timestamp."""
    store = ProvenanceStore(tmp_path / "p.json")
    e = store.add("NCT00095238", source="a", extractor="human")
    original_time = e.extracted_at
    store.save()
    store2 = ProvenanceStore(tmp_path / "p.json")
    assert store2.get("NCT00095238").extracted_at == original_time


def test_malformed_json_raises(tmp_path: Path):
    p = tmp_path / "p.json"
    p.write_text("not valid json{", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Cannot read provenance store"):
        ProvenanceStore(p)
