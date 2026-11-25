"""Materials CMSEI does not score yet (data/coverage.json). Used to say so out loud instead of dropping them silently."""
from __future__ import annotations
import json
import re
from . import classifier, taxonomy

_COV = json.loads((taxonomy.DATA / "coverage.json").read_text())
# A material that has since been scored leaves the gap list on its own.
GAPS = [m for m in _COV["materials"] if m["id"] not in taxonomy.MATERIALS]
_BY_ID = {m["id"]: m for m in GAPS}


def _phrase(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\- ]", " ", s.lower())).strip()


def mentions(*texts: str) -> list[str]:
    """Ids of unscored materials named in any of the given texts, in coverage-file order."""
    t = " " + re.sub(r"[^a-z0-9\- ]", " ", " ; ".join(classifier._norm(x) for x in texts if x)) + " "
    out = []
    for m in GAPS:
        for syn in [m["name"]] + m["synonyms"]:
            p = _phrase(syn)
            if p and re.search(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", t):
                out.append(m["id"])
                break
    return out


def name(mid: str) -> str:
    return _BY_ID[mid]["name"]


def public() -> dict:
    return {"version": _COV["version"], "compiled": _COV["compiled"], "note": _COV["note"], "status": _COV["status"],
            "scored": len(taxonomy.MATERIALS),
            "not_scored": [{k: m[k] for k in ("id", "name", "why", "usgs")} for m in GAPS]}
