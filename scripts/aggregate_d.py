"""Turn expert ratings of substitution difficulty (D) into data/expert_d.json.

  python3 -I scripts/aggregate_d.py --template experts.csv           # blank sheet, one row per material per expert slot
  python3 -I scripts/aggregate_d.py --in ratings.csv                 # aggregate; writes data/expert_d.json
  python3 -I scripts/aggregate_d.py --in ratings.csv --out /tmp/x.json

ratings.csv columns: expert_id,material,d,rationale
  d          0.5 to 1.5 (see docs/D-SCORING.md for the anchors)
  rationale  one plain sentence naming the application you had in mind. Required.
Rules: at least MIN_EXPERTS different experts per material or the material is left at D = 1.0 ("estimated"); one row per expert and
material; the result is the median. If the highest and lowest rating differ by more than MAX_SPREAD the material is marked as a
disagreement and the page says so. Expert ids are used only to count people and are not written to the output.
After writing, rebuild the taxonomy:  python3 -I scripts/build_taxonomy.py  then  python3 -I scripts/backtest_shocks.py
"""
import argparse
import csv
import datetime
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIN_EXPERTS = 5
MAX_SPREAD = 0.5


def read(path):
    ratings, problems = {}, []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for n, r in enumerate(csv.DictReader(f), start=2):
            try:
                who, mat = r["expert_id"].strip(), r["material"].strip()
                d, why = float(r["d"]), (r.get("rationale") or "").strip()
            except (KeyError, ValueError, AttributeError):
                problems.append(f"line {n}: could not read the row")
                continue
            if not who or not mat:
                problems.append(f"line {n}: expert_id and material are required")
            elif not 0.5 <= d <= 1.5:
                problems.append(f"line {n}: d must be between 0.5 and 1.5")
            elif not why:
                problems.append(f"line {n}: rationale is required")
            elif who in ratings.get(mat, {}):
                problems.append(f"line {n}: {who} already rated {mat}")
            else:
                ratings.setdefault(mat, {})[who] = d
    return ratings, problems


def aggregate(ratings, valid_ids, today=None):
    today = today or datetime.date.today().isoformat()
    out, left = {}, {}
    for mat, by in sorted(ratings.items()):
        if mat not in valid_ids:
            left[mat] = "not a scored material"
        elif len(by) < MIN_EXPERTS:
            left[mat] = f"only {len(by)} expert(s); need {MIN_EXPERTS}"
        else:
            v = sorted(by.values())
            out[mat] = {"d": round(statistics.median(v), 2), "n_experts": len(v), "min": v[0], "max": v[-1],
                        "disagreement": (v[-1] - v[0]) > MAX_SPREAD, "reviewed": today}
    return out, left


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp")
    ap.add_argument("--out", default=str(ROOT / "data" / "expert_d.json"))
    ap.add_argument("--template")
    a = ap.parse_args(argv)
    mats = json.loads((ROOT / "data" / "material_categories.json").read_text())["materials"]
    ids = {m["id"] for m in mats}
    if a.template:
        with open(a.template, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["expert_id", "material", "d", "rationale"])
            for m in mats:
                w.writerow(["", m["id"], "", ""])
        print("wrote", a.template)
        return 0
    if not a.inp:
        print(__doc__)
        return 2
    ratings, problems = read(a.inp)
    if problems:
        print("Fix these first:\n" + "\n".join(problems))
        return 1
    out, left = aggregate(ratings, ids)
    for m, why in left.items():
        print(f"left at D = 1.0: {m}: {why}")
    pathlib.Path(a.out).write_text(json.dumps({"version": "d-1", "rule": f"median of at least {MIN_EXPERTS} experts; disagreement if range > {MAX_SPREAD}", "materials": out}, indent=1))
    print("wrote", len(out), "materials to", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
