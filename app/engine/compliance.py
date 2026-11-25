"""Compliance screening (company layer). Maps a parts list to the public rules that may apply, using the countries a
supplier declared. It reports what a person should look at. It never says a company is or is not compliant.
Rules live in data/compliance_rules.json with sources and the date they were last reviewed. Not reviewed by counsel."""
from __future__ import annotations
import datetime as dt
import json
from . import taxonomy
from .bom import norm_country

_DATA = json.loads((taxonomy.DATA / "compliance_rules.json").read_text())
RULES = {r["id"]: r for r in _DATA["rules"]}
VERSION, LAST_REVIEWED, NOTE, TARIFFS_NOTE = _DATA["version"], _DATA["last_reviewed"], _DATA["review_note"], _DATA["tariffs_note"]
APPLIES_FLAG = {"dfars-252.225-7052": "defense", "sec-conflict-minerals": "sec_filer"}


def for_material(material_id: str) -> list[dict]:
    return [r for r in RULES.values() if material_id in r["materials"]]


def _covered_set(rule) -> set[str]:
    return {norm_country(c) for c in rule["covered_countries"]} - {None}


def _days_until(date_str: str, today: dt.date) -> int | None:
    try:
        return (dt.date.fromisoformat(date_str) - today).days
    except ValueError:
        return None


def report(rows: list[dict], flags: dict | None = None, today: dt.date | None = None) -> list[dict]:
    """`flags` may hold {"defense": bool, "sec_filer": bool} as the user stated them. Unstated means 'check'."""
    today = today or dt.date.today()
    flags = flags or {}
    out = []
    for rule in RULES.values():
        mats = set(rule["materials"])
        hit = [r for r in rows if mats & set(r["minerals"])]
        if not hit:
            continue
        covered = _covered_set(rule)
        counts = {"declared_covered": 0, "declared_clear": 0, "undeclared": 0}
        parts = []
        for r in hit:
            cands = [norm_country(r["origin"]), norm_country(r["processing"])]
            declared = [c for c in cands if c]
            if not declared:
                st = "undeclared"
            elif any(c in covered for c in declared):
                st = "declared_covered"
            else:
                st = "declared_clear"
            counts[st] += 1
            if st != "declared_clear":
                parts.append({"part": r["part"], "supplier": r["supplier"], "product": r["product"], "status": st,
                              "origin": r["origin"], "processing": r["processing"]})
        key = APPLIES_FLAG.get(rule["id"])
        applies = "check" if key is None or key not in flags else ("yes" if flags[key] else "no")
        if applies == "no":
            continue
        upcoming = []
        for d in rule["dates"]:
            n = _days_until(d["date"], today)
            if n is not None and n >= 0:
                upcoming.append({"date": d["date"], "what": d["what"], "days": n})
        out.append({"id": rule["id"], "regime": rule["regime"], "title": rule["title"], "applies_when": rule["applies_when"],
                    "applies": applies, "scope_note": rule["scope_note"], "origin_check": rule["origin_check"],
                    "covered_countries": rule["covered_countries"], "parts_in_scope": len(hit), "counts": counts, "parts": parts[:50],
                    "upcoming": upcoming, "sources": rule["sources"],
                    "meaning": ("Any part whose declared origin or processing country is on the covered list needs a closer look; undeclared parts cannot be cleared from this file."
                                if rule["origin_check"] == "covered" else
                                "Origin in China does not by itself trigger this law. A link to Xinjiang does, which a country field cannot show. Treat the list as a prompt for supplier questions.")})
    return out
