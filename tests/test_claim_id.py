"""Tests for the claim_id persistent identifier on BaselineRecord."""
from __future__ import annotations

from pathlib import Path

from mission_critical.baseline.store import BaselineStore


def test_new_record_gets_auto_claim_id(tmp_path: Path):
    store = BaselineStore(tmp_path / "b.json")
    rec = store.record("paper-1", pooled_estimate=1.0)
    assert rec.claim_id.startswith("cl_")
    assert len(rec.claim_id) == 11  # "cl_" + 8 hex chars


def test_two_new_records_get_distinct_claim_ids(tmp_path: Path):
    store = BaselineStore(tmp_path / "b.json")
    a = store.record("paper-a", pooled_estimate=1.0)
    b = store.record("paper-b", pooled_estimate=2.0)
    assert a.claim_id != b.claim_id


def test_overwrite_preserves_claim_id(tmp_path: Path):
    """Re-recording same paper_id keeps the same claim_id — the whole
    point of the HEPData-style persistent identifier."""
    store = BaselineStore(tmp_path / "b.json")
    v1 = store.record("sglt2i-hfpef-v1.0", pooled_estimate=0.80)
    original_id = v1.claim_id
    v2 = store.record(
        "sglt2i-hfpef-v1.0", pooled_estimate=0.81, overwrite=True,
    )
    assert v2.claim_id == original_id


def test_explicit_claim_id_respected(tmp_path: Path):
    store = BaselineStore(tmp_path / "b.json")
    rec = store.record(
        "paper-1", pooled_estimate=1.0, claim_id="cl_deadbeef",
    )
    assert rec.claim_id == "cl_deadbeef"


def test_json_roundtrip_preserves_claim_id(tmp_path: Path):
    store = BaselineStore(tmp_path / "b.json")
    rec = store.record("paper-1", pooled_estimate=1.0)
    original_id = rec.claim_id
    store.save()

    store2 = BaselineStore(tmp_path / "b.json")
    loaded = store2.get("paper-1")
    assert loaded is not None
    assert loaded.claim_id == original_id


def test_old_json_without_claim_id_loads_and_mints(tmp_path: Path):
    """Pre-claim_id on-disk records load cleanly; default factory
    mints a fresh claim_id at load-time (one-shot migration)."""
    p = tmp_path / "b.json"
    p.write_text(
        '{"schema_version":"0.1","records":{"old":{'
        '"paper_id":"old","recorded_at":"2026-04-19T00:00:00Z",'
        '"commit_sha":null,"pooled_estimate":1.0,"extra":{}'
        '}}}',
        encoding="utf-8",
    )
    store = BaselineStore(p)
    rec = store.get("old")
    assert rec is not None
    assert rec.claim_id.startswith("cl_")


def test_future_schema_extra_fields_ignored(tmp_path: Path):
    """A future BaselineRecord schema with extra fields must load
    without crashing on an older client."""
    p = tmp_path / "b.json"
    p.write_text(
        '{"schema_version":"0.1","records":{"x":{'
        '"paper_id":"x","recorded_at":"2026-04-19T00:00:00Z",'
        '"commit_sha":null,"pooled_estimate":1.0,"extra":{},'
        '"some_future_field":"value",'
        '"claim_id":"cl_abcd1234"'
        '}}}',
        encoding="utf-8",
    )
    store = BaselineStore(p)
    rec = store.get("x")
    assert rec is not None
    assert rec.claim_id == "cl_abcd1234"
