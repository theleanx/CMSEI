"""Scoring formula v1.1 (Full spec section 4.2). Pure functions, no I/O.

HHI is on a 0-10,000 scale (shares in percent). C = HHI/100. P = 0.3*raw/100 + 0.7*processing/100.
S = min(100, 100/(1+N_eff) * D). Base = 0.3C + 0.4P + 0.3S. Composite = min(100, Base * G).
"""
from __future__ import annotations

FORMULA_VERSION = "1.1"
WEIGHTS = (0.3, 0.4, 0.3)
RAW_STAGE_WEIGHT, PROC_STAGE_WEIGHT = 0.3, 0.7
FULL_CREDIT_SHARE = 5.0
G_CAP = 1.5
EFFECT = {"statement": 0.02, "proposed": 0.08, "enacted": 0.15, "ban": 0.30}
STAGE_RANK = {"statement": 1, "proposed": 2, "enacted": 3, "ban": 4}
TIER_NAMES = ("Low", "Moderate", "High", "Critical")
# credit given to a source by qualification status (spec 4.2: unverified or unqualified get none)
CREDIT_STATUS = {"qualified": True, "provisional": True, "unverified": False, "unqualified": False}


def tier_of(score: float) -> str:
    """Explicit inequalities: Low 0-30, Moderate (30,60], High (60,80], Critical (80,100]."""
    if score <= 30:
        return "Low"
    if score <= 60:
        return "Moderate"
    if score <= 80:
        return "High"
    return "Critical"


def hhi(shares) -> float:
    return float(sum(s * s for s in shares))


def n_eff(alt_sources) -> float:
    """Sum over non-dominant countries of min(1, global_share / 5), for sources that earn credit."""
    total = 0.0
    for a in alt_sources:
        if not a.get("included_in_n_alt", False):
            continue
        if not CREDIT_STATUS.get(a.get("qualification_status", "unverified"), False):
            continue
        total += min(1.0, float(a["global_share"]) / FULL_CREDIT_SHARE)
    return total


def s_score(n: float, d: float) -> float:
    return min(100.0, 100.0 / (1.0 + n) * d)


def p_score(raw_hhi: float, proc_hhi: float) -> float:
    return RAW_STAGE_WEIGHT * raw_hhi / 100.0 + PROC_STAGE_WEIGHT * proc_hhi / 100.0


def g_multiplier(stages) -> float:
    """G = 1.0 + sum of active event effects, capped at 1.5. `stages` is an iterable of stage names."""
    return min(G_CAP, 1.0 + sum(EFFECT.get(s, 0.0) for s in stages))


def combine(c: float, p: float, s: float, g: float = 1.0, w=WEIGHTS) -> dict:
    base = w[0] * c + w[1] * p + w[2] * s
    comp = min(100.0, base * g)
    return {"C": c, "P": p, "S": s, "G": g, "base": base, "composite": comp, "tier": tier_of(comp)}


def inputs_from_material(m: dict) -> dict:
    """Everything the formula needs, taken from a taxonomy record. This dict is the calculation payload."""
    return {
        "import_shares": [x["share"] for x in m["import"]["shares"]],
        "raw_hhi": m["raw_hhi_baseline"],
        "proc_hhi": m["processing_hhi_baseline"],
        "alternative_sources": [
            {k: a[k] for k in ("country", "global_share", "qualification_status", "included_in_n_alt")}
            for a in m["alternative_sources"]
        ],
        "d": m["substitution_difficulty"],
    }


def score_inputs(inp: dict, stages=(), w=WEIGHTS) -> dict:
    c = hhi(inp["import_shares"]) / 100.0
    p = p_score(inp["raw_hhi"], inp["proc_hhi"])
    n = n_eff(inp["alternative_sources"])
    s = s_score(n, inp["d"])
    g = g_multiplier(stages)
    out = combine(c, p, s, g, w)
    out["N_eff"] = n
    return out


def divergence_note(m: dict) -> bool:
    """Spec 4.11 item 3: production HHI exceeds import HHI by 30 or more (both /100)."""
    return (m["production"]["hhi"] - m["import"]["hhi"]) / 100.0 >= 30.0


def round_score(x: float) -> int:
    return int(x + 0.5)
