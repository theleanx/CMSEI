"""Add a material to the source file from two independent typed copies. Nothing is written unless the copies agree exactly.

  python3 -I scripts/merge_entry.py --source data/source_mcs2024.json --a entry_A.csv --b entry_B.csv \
      --material germanium --form metal --document "USGS MCS 2024, Germanium, pp. 70-71" --entered-by "Priyanshi Joshi,Ankit"

Each entry file has columns  material,group,country,value  (same layout as scripts/verify_transcription.py).
  group import      value = percent share of US imports for that country
  group production  value = world production quantity as printed, one row per country, "Other" included if printed
  group nir         value = net import reliance percent, country blank
Country spellings must match the source file's keys (for example DRC, SouthAfrica, Korea). Run with --material once per material.
Afterwards:  python3 -I scripts/build_taxonomy.py   then   python3 -I scripts/backtest_shocks.py
"""
import argparse
import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import verify_transcription as vt  # noqa: E402


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--material", required=True)
    ap.add_argument("--form", required=True, help="form the import table describes, for example metal, ore, oxide")
    ap.add_argument("--document", required=True, help="document and pages both people used")
    ap.add_argument("--entered-by", required=True, help="the two people, comma separated")
    a = ap.parse_args(argv)
    mid = a.material
    people = [p.strip() for p in a.entered_by.split(",") if p.strip()]
    if len(set(people)) != 2:
        print("Name two different people with --entered-by.")
        return 1
    ga, pa = vt.read_entry(a.a)
    gb, pb = vt.read_entry(a.b)
    if pa or pb:
        print("Problems reading the entries:\n" + "\n".join(pa + pb))
        return 1
    ga = {k: v for k, v in ga.items() if k[0] == mid}
    gb = {k: v for k, v in gb.items() if k[0] == mid}
    if not ga or not gb:
        print(f"Both entries need rows for {mid}.")
        return 1
    r = vt.compare(ga, gb)
    if r["mismatched"] or r["missing_in_entry"] or r["extra_in_entry"]:
        print("The two entries disagree. Nothing was written. Differences:")
        for k, x, y in r["mismatched"]:
            print(f"  {k}: A={x} B={y}")
        for k in r["missing_in_entry"]:
            print(f"  only in A: {k}")
        for k in r["extra_in_entry"]:
            print(f"  only in B: {k}")
        return 1
    imp = {c: v for (m, g, c), v in ga.items() if g == "import"}
    prod = {c: v for (m, g, c), v in ga.items() if g == "production"}
    nir = [v for (m, g, c), v in ga.items() if g == "nir"]
    bad = [k for k in ga if k[1] not in ("import", "production", "nir")]
    if bad or not imp or not prod or len(nir) != 1:
        print("Need at least one import row, one production row and exactly one nir row, and only those groups.")
        return 1
    if sum(imp.values()) > 100.5 or any(v < 0 for v in list(imp.values()) + list(prod.values())) or not 0 <= nir[0] <= 100:
        print("Import shares add to more than 100, a value is negative, or net import reliance is outside 0 to 100.")
        return 1
    src = pathlib.Path(a.source)
    d = json.loads(src.read_text())
    if mid in d["import"]:
        print(f"{mid} is already in the source file.")
        return 1
    d["import"][mid] = {"form": a.form, "shares": imp}
    d["production"][mid] = prod
    d["nir"][mid] = nir[0]
    d.setdefault("double_entry", {})[mid] = {"document": a.document, "entered_by": people, "date": datetime.date.today().isoformat(),
                                             "figures": len(ga)}
    src.write_text(json.dumps(d, indent=1))
    print(f"Added {mid}: {len(ga)} figures agree between the two entries.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
