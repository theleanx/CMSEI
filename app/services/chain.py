"""Append-only, hash-chained snapshot log (patent claim 5).

Each log entry stores the digest of the entry before it. The digest of an entry covers the whole snapshot in a
canonical serialisation plus the previous digest, so changing or removing any earlier entry breaks every digest
after it. `verify_chain` walks the log and also regenerates each score from the stored payload.
"""
from __future__ import annotations
import hashlib
import json

GENESIS = "0" * 64


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def h(obj) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def entry_body(sn) -> dict:
    """Everything a reader sees about a snapshot, except its database id and its later superseded date."""
    return {
        "material_id": sn.material_id, "formula_version": sn.formula_version, "taxonomy_version": sn.taxonomy_version,
        "data_as_of": sn.data_as_of, "source_snapshot": sn.source_snapshot, "events_hash": sn.events_hash,
        "payload": sn.payload, "payload_hash": sn.payload_hash, "composite": f"{sn.composite:.9f}", "tier": sn.tier,
        "grade": sn.grade, "uncertainty_hash": h(sn.uncertainty), "citations_hash": h(sn.citations),
        "published_at": sn.published_at.isoformat(),
    }


def entry_digest(body: dict, prev_digest: str) -> str:
    return hashlib.sha256((prev_digest + canonical(body)).encode()).hexdigest()
