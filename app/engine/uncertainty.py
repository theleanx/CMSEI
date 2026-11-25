"""Joint sensitivity run behind the "How sure is this score?" panel. Seeded, so it is reproducible.

Same method as the paper's Section V-A and supporting-materials/validation/exposure_sensitivity.py:
  weights      Dirichlet around 0.3/0.4/0.3, concentration 50 (about +/-0.07)
  D            uniform +/-0.2, kept inside 0.5-1.5
  event size   effect scaled by uniform 0.5-1.5
  shares       each import share +/-3 points (uniform, floor 0.5), renormalised to 100
  processing   processing-stage HHI moves by the same relative amount as import HHI
The range is the 5th to 95th percentile of the joint draws.

One addition for the platform: every source still marked "provisional" (listed, not yet reviewed by a person) is
credited or not with probability 0.5 in each draw. The official score credits none of them. The run also reports
the score if all of them were credited.
"""
from __future__ import annotations
import hashlib
import numpy as np
from . import scoring as sc

N_RUNS = 50_000
SEED_BASE = 20261124
TIERS = np.array(sc.TIER_NAMES)


def _seed(material_id: str) -> int:
    return SEED_BASE + int(hashlib.sha256(material_id.encode()).hexdigest()[:8], 16)


def _tier_idx(x):
    return np.where(x <= 30, 0, np.where(x <= 60, 1, np.where(x <= 80, 2, 3)))


def run(material_id: str, inp: dict, stages=(), n_runs: int = N_RUNS) -> dict:
    rng = np.random.default_rng(_seed(material_id))
    off = sc.score_inputs(inp, stages)
    ref_tier = off["tier"]
    w0 = np.array(sc.WEIGHTS)

    # weights only, for the weight-stability figure
    Ww = rng.dirichlet(w0 * 50, n_runs)
    base_w = Ww[:, 0] * off["C"] + Ww[:, 1] * off["P"] + Ww[:, 2] * off["S"]
    comp_w = np.minimum(100.0, base_w * off["G"])
    same_w = float((TIERS[_tier_idx(comp_w)] == ref_tier).mean())

    # everything together
    W = rng.dirichlet(w0 * 50, n_runs)
    d = np.clip(inp["d"] + rng.uniform(-0.2, 0.2, n_runs), 0.5, 1.5)
    g_base = sc.g_multiplier(stages)
    g = np.minimum(sc.G_CAP, 1.0 + (g_base - 1.0) * rng.uniform(0.5, 1.5, n_runs))
    shares = np.array(inp["import_shares"], float)
    other = max(0.0, 100.0 - shares.sum())
    cols = list(shares) + ([other] if other > 0 else [])
    noisy = np.clip(np.array(cols)[None, :] + rng.uniform(-3, 3, (n_runs, len(cols))), 0.5, None)
    noisy = 100.0 * noisy / noisy.sum(axis=1, keepdims=True)
    listed = noisy[:, : len(shares)]
    h_noisy = (listed ** 2).sum(axis=1)
    c = h_noisy / 100.0
    h_base = float((shares ** 2).sum()) or 1.0
    p = sc.RAW_STAGE_WEIGHT * inp["raw_hhi"] / 100.0 + sc.PROC_STAGE_WEIGHT * (inp["proc_hhi"] / 100.0) * (h_noisy / h_base)
    # alternate credit: verified sources count as they do officially; provisional ones with probability 0.5
    n_ver, prov = 0.0, []
    for a in inp["alternative_sources"]:
        if not a.get("included_in_n_alt", False):
            continue
        cr = min(1.0, float(a["global_share"]) / sc.FULL_CREDIT_SHARE)
        if sc.CREDIT_STATUS.get(a.get("qualification_status", "unverified"), False):
            n_ver += cr
        elif a.get("qualification_status") == "provisional":
            prov.append(cr)
    n = np.full(n_runs, n_ver)
    for cr in prov:
        n = n + cr * (rng.random(n_runs) < 0.5)
    s = np.minimum(100.0, 100.0 / (1.0 + n) * d)
    comp = np.minimum(100.0, (W[:, 0] * c + W[:, 1] * p + W[:, 2] * s) * g)

    lo, hi = float(np.percentile(comp, 5)), float(np.percentile(comp, 95))
    lo, hi = min(lo, off["composite"]), max(hi, off["composite"])
    ti = _tier_idx(comp)
    shares_t = {t: float((ti == i).mean()) for i, t in enumerate(sc.TIER_NAMES)}
    changed = 1.0 - shares_t.get(ref_tier, 0.0)

    # the score if every provisional source were credited
    inp_prov = dict(inp, alternative_sources=[dict(a, qualification_status="qualified") if a.get("qualification_status") == "provisional" else a
                                              for a in inp["alternative_sources"]])
    with_prov = sc.score_inputs(inp_prov, stages)
    return {
        "n_runs": n_runs, "seed": _seed(material_id), "method": "paper-section-V-A",
        "range_low": round(lo, 1), "range_high": round(hi, 1),
        "tier_shares": {k: round(v, 3) for k, v in shares_t.items()},
        "weights_only_same_tier": round(same_w, 3),
        "provisional_credit_composite": round(with_prov["composite"], 1), "provisional_credit_tier": with_prov["tier"],
        "provisional_sources": len(prov),
        "near_boundary": changed > 0.20,
        "tier_depends_on_alternates": with_prov["tier"] != ref_tier,
        "share_other_tier": round(changed, 3),
    }
