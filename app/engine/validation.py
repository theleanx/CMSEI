"""Back-test against documented export restrictions (pilot, small sample).

Question: did the index put the materials that later faced a government export restriction higher than the others?
Labels come from data/shocks.json (a registry with sources, not an exhaustive search). Scores are the official market-level
composites computed from the loaded USGS 2024 tables with no event layer. Compared with simple concentration baselines.
Everything is deterministic: the bootstrap and permutation tests use a fixed seed.
"""
from __future__ import annotations
import json
import numpy as np
from . import scoring as sc, taxonomy

SEED = 20261124
N_BOOT = 5000
N_PERM = 20000


def registry() -> dict:
    return json.loads((taxonomy.DATA / "shocks.json").read_text())


def auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """Mann-Whitney AUC with ties counted half."""
    pos, neg = scores[labels == 1], scores[labels == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    gt = (pos[:, None] > neg[None, :]).sum()
    eq = (pos[:, None] == neg[None, :]).sum()
    return float((gt + 0.5 * eq) / (len(pos) * len(neg)))


def features() -> dict[str, dict[str, float]]:
    out = {}
    for mid, m in taxonomy.MATERIALS.items():
        res = sc.score_inputs(sc.inputs_from_material(m), [])
        out[mid] = {"cmsei": res["composite"], "top_producer_share": m["production"]["shares"][0]["share"],
                    "production_hhi": m["production"]["hhi"], "import_hhi": m["import"]["hhi"]}
    return out


def _auc_for(feats, ids, pos_ids, key) -> float:
    labels = np.array([1 if i in pos_ids else 0 for i in ids])
    return round(auc(np.array([feats[i][key] for i in ids]), labels), 3)


def sensitivity(feats, ids, pos_ids) -> dict:
    """AUC when the weakest label is dropped (nickel: an ore ban, not a ban on the refined metal the data describes)
    and when only China-imposed restrictions count."""
    cases = {"all labels": set(pos_ids), "without nickel (ore ban)": set(pos_ids) - {"nickel"},
             "China-imposed only": {e["material_id"] for e in registry()["events"] if e["country"] == "China"}}
    out = {}
    for name, pos in cases.items():
        rest = [i for i in ids if i in pos or i not in set(pos_ids)]   # a dropped positive is removed, not turned into a negative
        out[name] = {"n_positive": len(pos), "n": len(rest),
                     **{k: _auc_for(feats, rest, pos, k) for k in ("cmsei", "top_producer_share", "production_hhi", "import_hhi")}}
    return out


def run() -> dict:
    reg = registry()
    pos_ids = sorted({e["material_id"] for e in reg["events"]})
    feats = features()
    ids = sorted(feats)
    labels = np.array([1 if i in pos_ids else 0 for i in ids])
    rng = np.random.default_rng(SEED)
    methods = {"cmsei": "CMSEI composite (official, no events)", "top_producer_share": "Top producer's world share",
               "production_hhi": "World-production HHI", "import_hhi": "US import HHI"}
    results = {}
    for key, label in methods.items():
        x = np.array([feats[i][key] for i in ids])
        a = auc(x, labels)
        idx_pos, idx_neg = np.where(labels == 1)[0], np.where(labels == 0)[0]
        boots = []
        for _ in range(N_BOOT):
            bp = rng.choice(idx_pos, len(idx_pos)); bn = rng.choice(idx_neg, len(idx_neg))
            sel = np.concatenate([bp, bn]); lab = np.concatenate([np.ones(len(bp), int), np.zeros(len(bn), int)])
            boots.append(auc(x[sel], lab))
        lo, hi = np.percentile(boots, [2.5, 97.5])
        perm = np.array([auc(x, rng.permutation(labels)) for _ in range(N_PERM)])
        p = float((1 + (perm >= a).sum()) / (1 + N_PERM))
        rank = {i: int(r) + 1 for r, i in enumerate(sorted(ids, key=lambda i: -feats[i][key]))}
        results[key] = {"label": label, "auc": round(a, 3), "ci95": [round(float(lo), 3), round(float(hi), 3)], "p_one_sided": round(p, 4),
                        "ranks_of_positives": {i: rank[i] for i in pos_ids}}
    diff_boot = []
    x1 = np.array([feats[i]["cmsei"] for i in ids]); x2 = np.array([feats[i]["top_producer_share"] for i in ids])
    idx_pos, idx_neg = np.where(labels == 1)[0], np.where(labels == 0)[0]
    for _ in range(N_BOOT):
        bp = rng.choice(idx_pos, len(idx_pos)); bn = rng.choice(idx_neg, len(idx_neg))
        sel = np.concatenate([bp, bn]); lab = np.concatenate([np.ones(len(bp), int), np.zeros(len(bn), int)])
        diff_boot.append(auc(x1[sel], lab) - auc(x2[sel], lab))
    dlo, dhi = np.percentile(diff_boot, [2.5, 97.5])
    d = results["cmsei"]["auc"] - results["top_producer_share"]["auc"]
    return {
        "registry_version": reg["version"], "formula_version": sc.FORMULA_VERSION, "source_vintage": taxonomy.SOURCE_VINTAGE,
        "n_materials": len(ids), "n_positive": int(labels.sum()), "positives": pos_ids, "seed": SEED, "n_boot": N_BOOT, "n_perm": N_PERM,
        "results": results, "sensitivity": sensitivity(feats, ids, pos_ids),
        "cmsei_minus_top_producer_share": {"auc_difference": round(d, 3), "ci95": [round(float(dlo), 3), round(float(dhi), 3)]},
        "reading": reading(results, d, dlo, dhi, int(labels.sum()), len(ids)),
        "limits": ["Sample is tiny: a handful of positives. Intervals are wide and a single material can move the result.",
                   "The registry is not an exhaustive search, so some negatives may be mislabelled.",
                   "The index uses 2023 production and 2019-22 import tables that are unverified transcriptions. Nickel's restriction (2020) predates the data.",
                   "The test checks ranking only. It says nothing about timing or size of any disruption.",
                   "Labels were built after the index design, with knowledge of the result. This is a pilot, not an out-of-sample test."],
    }


def reading(results, d, dlo, dhi, n_pos, n) -> str:
    c = results["cmsei"]
    sig = "does" if c["ci95"][0] > 0.5 else "does not"
    beats = ("The index scores higher than the plain top-producer-share baseline in this sample, but the interval for the difference includes zero."
             if dlo <= 0 <= dhi else
             ("The index beats the top-producer-share baseline and the interval excludes zero." if d > 0 else "The index does worse than the top-producer-share baseline and the interval excludes zero."))
    if d <= 0 and dlo <= 0 <= dhi:
        beats = "The index does no better than the plain top-producer-share baseline in this sample, and the interval for the difference includes zero."
    return (f"{n_pos} of {n} materials had a documented export restriction. The index ranks them with AUC {c['auc']} "
            f"(95% interval {c['ci95'][0]} to {c['ci95'][1]}), which {sig} clearly exceed chance (0.5). {beats}")
