"""W3C PROV-O export for the provenance store.

PROV-O (https://www.w3.org/TR/prov-o/) is the standard vocabulary for
expressing provenance relationships: an Entity was Derived From another
Entity, via an Activity, attributed to an Agent.

Mapping:
  - Each identifier (NCT / PMID / DOI) -> prov:Entity
  - Each extractor string -> prov:Agent
  - The extraction event -> prov:Activity (derivation)
  - commit_sha -> anchors the activity to a specific code version

JSON-LD output is readable by any PROV-consuming tool (e.g. Whole Tale,
RO-Crate ingestion, ELN systems). No prov4ml dependency — we emit
minimal JSON-LD directly to keep the dep surface small.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mission_critical.provenance.store import ProvenanceStore


PROV_CONTEXT = "https://www.w3.org/ns/prov"


def store_to_prov_o(store: ProvenanceStore) -> dict[str, Any]:
    """Serialize a ProvenanceStore to a PROV-O JSON-LD document.

    Returns a single dict with @context, @graph structure. Write to disk
    via json.dump or integrate into an RO-Crate.
    """
    graph: list[dict[str, Any]] = []
    agents: set[str] = set()

    for entry in store.all():
        entity_id = f"urn:mc:identifier:{entry.identifier}"
        agent_id = f"urn:mc:agent:{entry.extractor}"
        activity_id = f"urn:mc:extraction:{entry.identifier}"

        agents.add(entry.extractor)

        graph.append({
            "@id": entity_id,
            "@type": "prov:Entity",
            "prov:type": entry.kind,
            "mc:identifierValue": entry.identifier,
            "mc:source": entry.source,
            "mc:verified": entry.verified,
            "mc:extractedValues": entry.values,
        })

        activity: dict[str, Any] = {
            "@id": activity_id,
            "@type": "prov:Activity",
            "prov:startedAtTime": entry.extracted_at,
            "prov:wasAssociatedWith": {"@id": agent_id},
            "mc:extractionSource": entry.source,
        }
        if entry.commit_sha:
            activity["mc:commitSha"] = entry.commit_sha
        if entry.verified and entry.verified_at:
            activity["prov:endedAtTime"] = entry.verified_at
        graph.append(activity)

        graph.append({
            "@id": entity_id + "#generation",
            "@type": "prov:Generation",
            "prov:entity": {"@id": entity_id},
            "prov:activity": {"@id": activity_id},
            "prov:atTime": entry.extracted_at,
        })

    for agent_name in sorted(agents):
        graph.append({
            "@id": f"urn:mc:agent:{agent_name}",
            "@type": "prov:Agent",
            "prov:label": agent_name,
        })

    return {
        "@context": {
            "prov": PROV_CONTEXT + "#",
            "mc": "urn:mission-critical:provenance:",
        },
        "@graph": graph,
    }


def write_prov_o(store: ProvenanceStore, out_path: Path | str) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = store_to_prov_o(store)
    out.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return out
