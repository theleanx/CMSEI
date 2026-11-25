"""Explanation sentence for a confirmed event (patent claims 1 and 8).

The sentence is made by filling a stored template with fields of a validated extraction record. The effect value comes
from the severity table. No language model writes or edits this text, and the free-text quotation is not used in it.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from . import scoring as sc, taxonomy

_T = json.loads((Path(__file__).resolve().parent.parent.parent / "data" / "explanation_templates.json").read_text())
TEMPLATE_VERSION = _T["version"]
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def explain(rec: dict, counted: bool = True) -> str:
    """`rec` needs country, material (a tracked material id), instrument, stage, effective_date, host and tier.
    Raises ValueError for anything that a validated record could not contain, so unvalidated text cannot get through."""
    stage = rec.get("stage")
    if stage not in _T["templates"]:
        raise ValueError("unknown stage")
    mid = rec.get("material")
    if mid not in taxonomy.MATERIALS:
        raise ValueError("untracked material")
    instr = rec.get("instrument")
    if instr not in _T["instrument_phrase"]:
        raise ValueError("unknown instrument")
    country = rec.get("country")
    from ..worker import gate            # the closed country list lives with the event gate
    if country not in gate.COUNTRIES:
        raise ValueError("unknown country")
    d = rec.get("effective_date")
    if d is not None and not _DATE.fullmatch(d):
        raise ValueError("bad date")
    host = rec.get("host")
    if host not in taxonomy.ALLOWLIST["hosts"]:
        raise ValueError("host not allowlisted")
    tier = str(taxonomy.ALLOWLIST["hosts"][host]["tier"])
    effect = f"{sc.EFFECT.get(stage, 0.0):.2f}"                      # from the severity table, never from the record
    text = _T["templates"][stage].format(
        country=country, material=taxonomy.MATERIALS[mid]["name"].lower(), instrument=_T["instrument_phrase"][instr],
        date=f", effective {d}" if d else "", effect=effect)
    text += _T["suffix"].format(host=host, tier=_T["source_label"].get(tier, "source"))
    if not counted:
        text += _T["shadow_suffix"]
    return text


def explain_record(r, counted: bool | None = None) -> str | None:
    """Sentence for an EventRecord row, or None when the record is not a validated event."""
    if r.status in ("rejected",) or not (r.material_id and r.country and r.stage and r.instrument):
        return None
    try:
        return explain({"country": r.country, "material": r.material_id, "instrument": r.instrument, "stage": r.stage,
                        "effective_date": r.effective_date, "host": r.source_host},
                       counted=(r.status == "active") if counted is None else counted)
    except ValueError:
        return None
