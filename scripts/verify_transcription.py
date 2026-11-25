"""Double-entry check of the data file against the published tables.

A second person reads the USGS table (PDF or the data release) and types the figures into a CSV WITHOUT looking at the data file.
This script compares the two and lists every difference. Agreement between two independent entries is the evidence that the
digits were copied correctly. It does not check that the right table was used: the CSV must name the document and page.

  python3 -I scripts/verify_transcription.py data/source_mcs2024.json entry.csv

entry.csv columns:  material,group,country,value
  group   import      value = percent share of US imports (the table's percentage for that country)
          production  value = world production quantity as printed in the table, for that country
          nir         value = net import reliance percent (country left blank)
Exit status 0 only if every figure in the data file was entered, matched, and nothing extra was entered.
"""
import csv
import json
import sys


def load(source):
    d = json.load(open(source))
    want = {}
    for mid, v in d["import"].items():
        for c, x in v["shares"].items():
            want[(mid, "import", c)] = float(x)
    for mid, v in d["production"].items():
        for c, x in v.items():
            want[(mid, "production", c)] = float(x)
    for mid, x in d["nir"].items():
        want[(mid, "nir", "")] = float(x)
    return want


def read_entry(path):
    got, problems = {}, []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for n, r in enumerate(csv.DictReader(f), start=2):
            try:
                key = (r["material"].strip(), r["group"].strip(), (r.get("country") or "").strip())
                if key in got:
                    problems.append(f"line {n}: duplicate entry for {key}")
                got[key] = float(r["value"].replace(",", ""))
            except (KeyError, ValueError, AttributeError):
                problems.append(f"line {n}: could not read the row")
    return got, problems


def compare(want, got, tol=1e-9):
    mismatched = sorted((k, want[k], got[k]) for k in want if k in got and abs(want[k] - got[k]) > tol)
    missing = sorted(k for k in want if k not in got)
    extra = sorted(k for k in got if k not in want)
    matched = sum(1 for k in want if k in got and abs(want[k] - got[k]) <= tol)
    return {"matched": matched, "mismatched": mismatched, "missing_in_entry": missing, "extra_in_entry": extra, "total": len(want)}


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    want = load(argv[1])
    got, problems = read_entry(argv[2])
    r = compare(want, got)
    print(f"{r['matched']} of {r['total']} figures agree.")
    for k, a, b in r["mismatched"]:
        print(f"DIFFERENT  {k[0]} / {k[1]} / {k[2] or '-'}: data file {a:g}, second entry {b:g}")
    for k in r["missing_in_entry"]:
        print(f"NOT ENTERED  {k[0]} / {k[1]} / {k[2] or '-'}")
    for k in r["extra_in_entry"]:
        print(f"NOT IN DATA FILE  {k[0]} / {k[1]} / {k[2] or '-'}")
    for p in problems:
        print("PROBLEM", p)
    ok = not (r["mismatched"] or r["missing_in_entry"] or r["extra_in_entry"] or problems)
    print("RESULT: figures agree. Record the check in the admin console." if ok else "RESULT: do not record a check until every difference is resolved against the published table.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
