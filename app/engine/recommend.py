"""Deterministic recommendation selection (spec 4.5). Region and volume are used here only, in memory.
They never touch the score and are never stored."""
from __future__ import annotations
import json
import pathlib
from .taxonomy import REGIONS

DATA = pathlib.Path(__file__).resolve().parent.parent.parent / "data"
RULES = {r["id"]: r for r in json.loads((DATA / "recommendations.json").read_text())["rules"]}

REGION_CHOICES = [
    ("china", "China", "CN"), ("apac", "Other Asia-Pacific", "APAC"), ("europe", "Europe", "EU"),
    ("na", "North America (incl. domestic)", "NA"), ("other", "Other regions (Africa, Latin America, Middle East, Russia, Central Asia)", "OTHER"),
    ("diversified", "Diversified (multiple regions)", None), ("unsure", "Not sure", None),
]
VOLUME_CHOICES = [("small", "Small (occasional or low volume)"), ("medium", "Medium (regular ongoing use)"),
                  ("large", "Large (high volume or continuous)")]
REGION_KEYS = {k for k, _, _ in REGION_CHOICES}
VOLUME_KEYS = {k for k, _ in VOLUME_CHOICES}


def _region_code(key):
    for k, _, code in REGION_CHOICES:
        if k == key:
            return code
    return None


def select(material: dict, tier: str, region: str | None, volume: str | None, scenario: bool = False) -> list:
    """Returns a list of {rule_id, text, guidance_basis, scenario}. 1-3 items."""
    high = tier in ("High", "Critical")
    dom_region = REGIONS.get(material["dominant_country"])
    code = _region_code(region) if region else None
    out = []
    if not high:
        out.append(("R3", {"tier": tier}))
    elif region in (None, "diversified", "unsure", "other") or code in (None, "OTHER"):
        out.append(("R4", {"tier": tier}))
    elif code == dom_region and (code != "CN" or material["dominant_country"] == "China"):
        alts = [a["country"] for a in sorted(material["alternative_sources"], key=lambda a: -a["global_share"])
                if a["included_in_n_alt"] and a["country"] != material["dominant_country"]][:3]
        out.append(("R1", {"alternatives": ", ".join(alts) if alts else "none listed"}))
    else:
        out.append(("R2", {}))
    if high and out[0][0] in ("R1", "R2", "R4"):
        if volume == "large":
            out.append(("R5", {}))
        elif volume == "small":
            out.append(("R6", {}))
    res = []
    for rid, fmt in out:
        r = RULES[rid]
        res.append({"rule_id": rid, "text": r["text"].format(**fmt) if fmt else r["text"],
                    "guidance_basis": r["guidance_basis"], "scenario": scenario})
    return res
