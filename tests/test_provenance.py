"""Tests for provenance store."""
from __future__ import annotations

from pathlib import Path

import pytest

from mission_critical.provenance.store import (
    DriftRecord,
    ProvenanceStore,
    _classify,
    _classify_change,
    _is_numeric,
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


# --- classify_diffs + DriftRecord ----------------------------------

def test_is_numeric_excludes_bool():
    """Python's `isinstance(True, int) == True` quirk per lessons.md —
    booleans must NOT count as numeric for drift classification."""
    assert _is_numeric(1) is True
    assert _is_numeric(1.5) is True
    assert _is_numeric(True) is False
    assert _is_numeric(False) is False
    assert _is_numeric("1") is False
    assert _is_numeric(None) is False


def test_classify_change_null_transition_wins_over_type():
    """old=int, new=None is a null_transition, not a type_changed —
    extraction-loss is the more actionable interpretation."""
    assert _classify_change(8442, None) == "null_transition"
    assert _classify_change(None, 8442) == "null_transition"


def test_classify_change_int_float_same_bucket():
    """int↔float is NOT type_changed. Extractors legitimately emit
    N=1 one day and 1.0 the next; value drift matters, type doesn't."""
    assert _classify_change(1, 2.0) == "value_changed"
    assert _classify_change(1.0, 2) == "value_changed"


def test_classify_change_numeric_to_string_is_type_changed():
    """int → str is a type flip — same value in different form is the
    extractor lying about the schema, not real data drift."""
    assert _classify_change(8442, "8442") == "type_changed"
    assert _classify_change("8442", 8442) == "type_changed"


def test_classify_change_different_non_numeric_types():
    assert _classify_change("a", ["a"]) == "type_changed"
    assert _classify_change({"x": 1}, [1]) == "type_changed"


def test_classify_change_same_type_different_value():
    assert _classify_change("PARADIGM", "VICTORIA") == "value_changed"
    assert _classify_change(8442, 1807) == "value_changed"


def test_classify_diffs_added_key(tmp_path: Path):
    """Key not in stored entry → 'added', distinct from null_transition."""
    store = ProvenanceStore(tmp_path / "p.json")
    store.add("NCT00095238", source="a", extractor="human", values={"N": 8442})
    records = store.classify_diffs("NCT00095238", {"HR": 0.80})
    assert len(records) == 1
    assert records[0] == DriftRecord(
        key="HR", old_value=None, new_value=0.80, change_class="added",
    )


def test_classify_diffs_null_transition(tmp_path: Path):
    """Extractor previously returned a value, now returns None."""
    store = ProvenanceStore(tmp_path / "p.json")
    store.add(
        "NCT00095238", source="a", extractor="human",
        values={"N": 8442, "HR": 0.80},
    )
    records = store.classify_diffs("NCT00095238", {"N": None})
    assert len(records) == 1
    assert records[0].change_class == "null_transition"
    assert records[0].old_value == 8442
    assert records[0].new_value is None


def test_classify_diffs_type_changed(tmp_path: Path):
    """Extractor schema flipped — was int, now str."""
    store = ProvenanceStore(tmp_path / "p.json")
    store.add("NCT00095238", source="a", extractor="human", values={"N": 8442})
    records = store.classify_diffs("NCT00095238", {"N": "8442"})
    assert len(records) == 1
    assert records[0].change_class == "type_changed"


def test_classify_diffs_value_changed(tmp_path: Path):
    """The lessons.md 'Not Randomized 1,807' case: same key, same type,
    real semantic drift. This is the class that MUST fire on the
    Verquvo VICTORIA-style extraction bug."""
    store = ProvenanceStore(tmp_path / "p.json")
    store.add("NCT00095238", source="a", extractor="human", values={"N": 8442})
    records = store.classify_diffs("NCT00095238", {"N": 1807})
    assert len(records) == 1
    assert records[0].change_class == "value_changed"
    assert records[0].old_value == 8442
    assert records[0].new_value == 1807


def test_classify_diffs_tolerance_absorbs_noise(tmp_path: Path):
    """Float rerun jitter — HR 0.80 vs 0.7999999 — must NOT surface
    when caller specifies a tolerance they don't care below."""
    store = ProvenanceStore(tmp_path / "p.json")
    store.add("NCT00095238", source="a", extractor="human", values={"HR": 0.80})
    records = store.classify_diffs(
        "NCT00095238", {"HR": 0.7999999}, float_tol=1e-5,
    )
    assert records == []


def test_classify_diffs_tolerance_does_not_hide_real_drift(tmp_path: Path):
    """Tolerance must NOT swallow a real HR flip from 0.80 to 0.90."""
    store = ProvenanceStore(tmp_path / "p.json")
    store.add("NCT00095238", source="a", extractor="human", values={"HR": 0.80})
    records = store.classify_diffs(
        "NCT00095238", {"HR": 0.90}, float_tol=0.01,
    )
    assert len(records) == 1
    assert records[0].change_class == "value_changed"


def test_classify_diffs_default_tolerance_zero(tmp_path: Path):
    """With no --float-tol, even tiny float drift surfaces — same
    semantics as the old diff_values."""
    store = ProvenanceStore(tmp_path / "p.json")
    store.add("NCT00095238", source="a", extractor="human", values={"HR": 0.80})
    records = store.classify_diffs("NCT00095238", {"HR": 0.7999999})
    assert len(records) == 1
    assert records[0].change_class == "value_changed"


def test_classify_diffs_multiple_records(tmp_path: Path):
    """All four drift classes can co-occur in one extraction run."""
    store = ProvenanceStore(tmp_path / "p.json")
    store.add(
        "NCT00095238", source="a", extractor="human",
        values={"N": 8442, "HR": 0.80, "deaths": 711},
    )
    records = store.classify_diffs("NCT00095238", {
        "N": 1807,              # value_changed
        "HR": "0.80",           # type_changed (float -> str)
        "deaths": None,         # null_transition
        "new_metric": 42,       # added
    })
    by_key = {r.key: r for r in records}
    assert by_key["N"].change_class == "value_changed"
    assert by_key["HR"].change_class == "type_changed"
    assert by_key["deaths"].change_class == "null_transition"
    assert by_key["new_metric"].change_class == "added"


def test_classify_diffs_unchanged_keys_omitted(tmp_path: Path):
    store = ProvenanceStore(tmp_path / "p.json")
    store.add(
        "NCT00095238", source="a", extractor="human",
        values={"N": 8442, "HR": 0.80},
    )
    records = store.classify_diffs("NCT00095238", {"N": 8442, "HR": 0.81})
    assert len(records) == 1
    assert records[0].key == "HR"


def test_classify_diffs_unknown_identifier_raises(tmp_path: Path):
    store = ProvenanceStore(tmp_path / "p.json")
    with pytest.raises(KeyError):
        store.classify_diffs("NCT99999999", {"N": 1})


def test_drift_record_to_dict():
    r = DriftRecord(key="N", old_value=8442, new_value=1807, change_class="value_changed")
    assert r.to_dict() == {
        "key": "N", "old_value": 8442, "new_value": 1807,
        "change_class": "value_changed",
    }


def test_drift_record_is_frozen():
    """DriftRecord must be immutable so test assertions don't accidentally
    mutate shared records across parameterized tests."""
    r = DriftRecord(key="N", old_value=1, new_value=2, change_class="value_changed")
    with pytest.raises(AttributeError):
        r.key = "X"  # type: ignore[misc]
