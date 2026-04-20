"""Tests for W3C PROV-O export of ProvenanceStore."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mission_critical.provenance.store import ProvenanceStore
from mission_critical.provenance.prov import store_to_prov_o, write_prov_o


def test_prov_export_structure(tmp_path: Path):
    store = ProvenanceStore(tmp_path / "p.json")
    store.add(
        "NCT00095238",
        source="paradigm-hf.pdf:p12",
        extractor="human",
        values={"N": 8442, "HR": 0.80},
        verified=True,
    )
    doc = store_to_prov_o(store)
    assert "@context" in doc
    assert "@graph" in doc
    # Should have Entity + Activity + Generation + Agent
    types = {n.get("@type") for n in doc["@graph"] if isinstance(n, dict)}
    assert "prov:Entity" in types
    assert "prov:Activity" in types
    assert "prov:Agent" in types


def test_prov_export_encodes_extracted_values(tmp_path: Path):
    store = ProvenanceStore(tmp_path / "p.json")
    store.add(
        "NCT00095238",
        source="paper:p12",
        extractor="tool",
        values={"N": 8442, "HR": 0.80},
    )
    doc = store_to_prov_o(store)
    entity = next(n for n in doc["@graph"]
                  if n.get("@type") == "prov:Entity")
    assert entity["mc:extractedValues"]["N"] == 8442
    assert entity["mc:extractedValues"]["HR"] == 0.80


def test_prov_export_commit_sha_on_activity(tmp_path: Path):
    store = ProvenanceStore(tmp_path / "p.json")
    store.add("NCT00095238", source="a", extractor="tool",
              commit_sha="abc1234")
    doc = store_to_prov_o(store)
    activity = next(n for n in doc["@graph"]
                    if n.get("@type") == "prov:Activity")
    assert activity["mc:commitSha"] == "abc1234"


def test_write_prov_o_emits_valid_json(tmp_path: Path):
    store = ProvenanceStore(tmp_path / "p.json")
    store.add("10.1234/foo", source="journal:issue:p5", extractor="human")
    out_path = tmp_path / "provenance.jsonld"
    result = write_prov_o(store, out_path)
    assert result == out_path
    reloaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert "@graph" in reloaded
    assert "@context" in reloaded


def test_empty_store_emits_empty_graph(tmp_path: Path):
    store = ProvenanceStore(tmp_path / "p.json")
    doc = store_to_prov_o(store)
    assert doc["@graph"] == []


def test_three_identifiers_produce_nine_graph_nodes(tmp_path: Path):
    """Each identifier -> 3 nodes (Entity, Activity, Generation) plus
    one Agent per unique extractor. 3 ids + 1 extractor = 10 nodes."""
    store = ProvenanceStore(tmp_path / "p.json")
    store.add("NCT00000001", source="a", extractor="tool")
    store.add("NCT00000002", source="b", extractor="tool")
    store.add("NCT00000003", source="c", extractor="tool")
    doc = store_to_prov_o(store)
    assert len(doc["@graph"]) == 3 * 3 + 1  # 9 per-id + 1 agent
