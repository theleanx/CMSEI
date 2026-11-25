"""Joint sensitivity run behind the "How sure is this score?" panel (spec 4.10). Seeded, so it is reproducible.

Perturbs together: weights (Dirichlet around 0.3/0.4/0.3, about +/-0.07), difficulty D (+/-0.2, kept in 0.5-1.5),
event size (+/-50%), import shares (+/-3 points, renormalised), and alternate-source credit (every provisional
source is credited or not with probability 0.5, because no source has been qualified by a person yet).
"""
from __future__ import annotations
import hashlib
import random
from . import scoring as sc

N_RUNS = 2000
SEED_BASE = 20261124


def _seed(material_id: str) -> int:
    return SEED_BASE + int(hashlib.sha256(material_id.encode()).hexdigest()[:8], 16)


def _dirichlet(rng, alpha):
    g = [rng.gammavariate(a, 1.0) for a in alpha]
    t = sum(g)
    return [x / t for x in g]


def run(material_id: str, inp: dict, stages=(), n_runs: int = N_RUNS) -> dict:
    rng = random.Random(_seed(material_id))
    official = sc.score_inputs(inp, stages)
    ref_tier = official["tier"]
    scores, tiers_all, tiers_w = [], [], []
    shares = list(inp["import_shares"])
    other = max(0.0, 100.0 - sum(shares))
    for _ in range(n_runs):
        # weights only (for the weight-stability figure)
        w = _dirichlet(rng, [0.3 * 50, 0.4 * 50, 0.3 * 50])
        tw = sc.combine(official["C"], official["P"], official["S"], official["G"], w)["tier"]
        tiers_w.append(tw)
        # everything together
        d = min(1.5, max(0.5, inp["d"] + rng.uniform(-0.2, 0.2)))
        noisy = [max(0.1, s + rng.uniform(-3, 3)) for s in shares] + [max(0.0, other + rng.uniform(-3, 3))]
        tot = sum(noisy)
        noisy = [100.0 * x / tot for x in noisy[:-1]]
        c = sc.hhi(noisy) / 100.0
        alts = []
        for a in inp["alternative_sources"]:
            a2 = dict(a)
            if a2.get("qualification_status") == "provisional":
                a2["qualification_status"] = "qualified" if rng.random() < 0.5 else "unverified"
            alts.append(a2)
        s = sc.s_score(sc.n_eff(alts), d)
        g = 1.0 + (sc.g_multiplier(stages) - 1.0) * rng.uniform(0.5, 1.5)
        g = min(sc.G_CAP, g)
        res = sc.combine(c, official["P"], s, g, w)
        scores.append(res["composite"])
        tiers_all.append(res["tier"])
    scores.sort()
    lo, hi = scores[int(0.05 * n_runs)], scores[int(0.95 * n_runs) - 1]
    lo, hi = min(lo, official["composite"]), max(hi, official["composite"])
    # what the score would be if no provisional alternate source were credited at all
    inp0 = dict(inp, alternative_sources=[dict(a, qualification_status="unverified") if a.get("qualification_status") == "provisional" else a
                                          for a in inp["alternative_sources"]])
    no_credit = sc.score_inputs(inp0, stages)
    shares_t = {t: sum(1 for x in tiers_all if x == t) / n_runs for t in sc.TIER_NAMES}
    same_w = sum(1 for x in tiers_w if x == ref_tier) / n_runs
    changed = 1.0 - shares_t.get(ref_tier, 0.0)
    return {
        "n_runs": n_runs, "seed": _seed(material_id),
        "range_low": round(lo, 1), "range_high": round(hi, 1),
        "tier_shares": {k: round(v, 3) for k, v in shares_t.items()},
        "weights_only_same_tier": round(same_w, 3),
        "no_alternate_credit_composite": round(no_credit["composite"], 1), "no_alternate_credit_tier": no_credit["tier"],
        "near_boundary": changed > 0.20,
        "tier_depends_on_alternates": no_credit["tier"] != ref_tier,
        "share_other_tier": round(changed, 3),
    }
