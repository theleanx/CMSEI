"""Freeze the current scores as a forecast, before any outcome is known (writes data/prospective_forecast.json).

  python3 -I scripts/freeze_forecast.py --version fc-1 --start 2026-12-01 --end 2027-11-30

Refuses to overwrite an existing forecast file. A new forecast gets a new version and a new file name is NOT used: keep the old
file in git history and bump the version, so the earlier freeze stays on record. The commit that adds this file is the
timestamp that matters, so commit it before the window opens.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.engine import scoring as sc, taxonomy, validation  # noqa: E402

PLAN = {
    "question": "Do the frozen scores rank materials that later face a government export restriction above the others?",
    "positive": "A government in a producing country announces a licensing requirement, quota or ban on exports of the material or its main compounds inside the window, recorded by an official or law-firm source in data/shocks.json.",
    "measures": ["CMSEI composite (no events)", "top producer's world share", "world-production HHI", "US import HHI"],
    "statistic": "AUC on the frozen values, reported with the number of positives.",
    "h1": "CMSEI AUC is above 0.5.",
    "h2": "CMSEI AUC is at least the top-producer-share AUC.",
    "decision_rule": "If h2 fails with at least 3 positives, the front page says the index does not beat simple concentration, and the index is described as a view of concentration, not a predictor.",
    "not_allowed": ["changing the frozen values", "adding or removing materials from the frozen set", "choosing positives after seeing scores"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    a = ap.parse_args()
    out = ROOT / "data" / validation.FORECAST
    if out.exists():
        print("A forecast file already exists. Keep it. Freeze a new one only under a new version after moving the old one in git history.")
        return 1
    feats = validation.features()
    tax = (ROOT / "data" / "material_categories.json").read_bytes()
    fc = {"version": a.version, "frozen_on": datetime.date.today().isoformat(), "window": {"start": a.start, "end": a.end},
          "formula_version": sc.FORMULA_VERSION, "taxonomy_version": taxonomy.TAXONOMY_VERSION, "source_vintage": taxonomy.SOURCE_VINTAGE,
          "taxonomy_sha256": hashlib.sha256(tax).hexdigest(),
          "d_note": "D was 1.0 (estimated) for every material when frozen.", "plan": PLAN,
          "ranking": [{"id": i, **{k: round(v, 3) for k, v in feats[i].items()}} for i in sorted(feats, key=lambda i: -feats[i]["cmsei"])]}
    fc["content_sha256"] = validation.forecast_hash(fc)
    out.write_text(json.dumps(fc, indent=1))
    print("frozen", len(fc["ranking"]), "materials; hash", fc["content_sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
