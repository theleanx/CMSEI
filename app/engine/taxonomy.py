"""Loads the reference data files once (spec 2)."""
from __future__ import annotations
import json
import pathlib

DATA = pathlib.Path(__file__).resolve().parent.parent.parent / "data"


def _load(name):
    return json.loads((DATA / name).read_text())


_TAX = _load("material_categories.json")
TAXONOMY_VERSION = _TAX["taxonomy_version"]
SOURCE_VINTAGE = _TAX["source_vintage"]
SOURCE_NOTE = _TAX["source_note"]
MATERIALS = {m["id"]: m for m in _TAX["materials"]}
_RCM = _load("region_country_map.json")
REGIONS = {c["country"]: c["region_code"] for c in _RCM["countries"]}
SECTORS = _load("sectors.json")
ALLOWLIST = _load("sources_allowlist.json")


def material_ids():
    return list(MATERIALS)
