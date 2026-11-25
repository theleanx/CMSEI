"""Builds data/material_categories.json from data/source_mcs2024.json plus the hand-curated tables below.

Run from the repo root:  python3 -I scripts/build_taxonomy.py

Rules (Full spec sections 2, 4.2, 4.8):
  - HHI is on a 0-10,000 scale. Import HHI counts the "other" bucket as zero (lower bound).
  - raw_hhi_baseline is the HHI of 2023 mine/primary production shares. Unnamed "Other" is in the
    denominator and counts as zero concentration.
  - processing_hhi_baseline is a REAL processing-stage figure only for cobalt and rare earths (IEA,
    top supplier only, lower bound). Everywhere else it is the production figure and the processing
    grade is C ("Indicative").
  - Alternate sources are every non-dominant named producer. Their qualification_status is
    "provisional": credited in N_eff, flagged, and the uncertainty range spans N_eff from 0 to full credit.
  - D (substitution difficulty) is 1.0 for every material and marked "estimated". It needs expert review.
  - trade_codes are left empty. They must be mapped by a person; none are guessed here.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
import argparse
_ap = argparse.ArgumentParser()
_ap.add_argument("--source", default="data/source_mcs2024.json", help="source file in the same layout as data/source_mcs2024.json")
_ap.add_argument("--out", default="data/material_categories.json")
_ap.add_argument("--expert-d", default="data/expert_d.json", help="output of scripts/aggregate_d.py; absent means D stays 1.0 (estimated)")
_ap.add_argument("--processing", default="data/processing_stage.json")
_args = _ap.parse_args()
SRC = json.loads((ROOT / _args.source).read_text())
# Edition and years come from the source file's optional "edition" block. Absent means the 2024 edition, so the shipped file rebuilds unchanged.
ED = {"mcs_edition": 2024, "production_year": 2023, "import_period": "2019-22", "import_year": 2022}
ED.update(SRC.get("edition", {}))

COUNTRY = {
    "SouthAfrica": "South Africa", "SaudiArabia": "Saudi Arabia", "NewCaledonia": "New Caledonia",
    "PNG": "Papua New Guinea", "DRC": "DR Congo", "US": "United States", "Korea": "South Korea",
    "SierraLeone": "Sierra Leone",
}
def cname(c):
    return COUNTRY.get(c, c)

NAMES = {
    "arsenic": ("Arsenic", "Semiconductors and chemicals"),
    "barite": ("Barite", "Industrial minerals"),
    "bauxite": ("Bauxite (aluminum ore)", "Industrial minerals"),
    "bismuth": ("Bismuth", "Metals and alloys"),
    "chromium": ("Chromium", "Metals and alloys"),
    "cobalt": ("Cobalt", "Battery and energy materials"),
    "fluorspar": ("Fluorspar", "Industrial minerals"),
    "gallium": ("Gallium", "Semiconductors and chemicals"),
    "indium": ("Indium", "Semiconductors and chemicals"),
    "lithium": ("Lithium", "Battery and energy materials"),
    "magnesium-metal": ("Magnesium metal", "Metals and alloys"),
    "nickel": ("Nickel", "Battery and energy materials"),
    "niobium": ("Niobium", "Metals and alloys"),
    "rare-earths": ("Rare earths", "Battery and energy materials"),
    "tantalum": ("Tantalum", "Metals and alloys"),
    "tin": ("Tin", "Metals and alloys"),
    "vanadium": ("Vanadium", "Metals and alloys"),
    "zinc": ("Zinc", "Metals and alloys"),
    "zirconium-hafnium": ("Zirconium and hafnium", "Metals and alloys"),
    # In scope but built only when the source file carries their tables (see docs/ADD-MATERIAL.md and data/coverage.json).
    "antimony": ("Antimony", "Metals and alloys"),
    "germanium": ("Germanium", "Semiconductors and chemicals"),
    "graphite": ("Graphite", "Battery and energy materials"),
    "tellurium": ("Tellurium", "Semiconductors and chemicals"),
    "tungsten": ("Tungsten", "Metals and alloys"),
}

# Plain-language phrases a non-expert might type. Used by the offline classifier and as classifier context.
SYN = {
    "arsenic": ["arsenic", "gallium arsenide", "gaas wafers", "wood preservative", "arsenic trioxide"],
    "barite": ["barite", "baryte", "barium sulfate", "drilling mud", "drilling fluid weighting"],
    "bauxite": ["bauxite", "aluminum ore", "aluminium ore", "alumina feedstock", "aluminum smelting feedstock"],
    "bismuth": ["bismuth", "lead-free solder additive", "bismuth alloys", "pharmaceutical bismuth"],
    "chromium": ["chromium", "chrome", "chromite", "ferrochrome", "stainless steel", "stainless steel alloying", "chrome plating"],
    "cobalt": ["cobalt", "cobalt sulfate", "battery cathode cobalt", "superalloy cobalt", "nmc cathode"],
    "fluorspar": ["fluorspar", "fluorite", "hydrofluoric acid feedstock", "acid grade fluorspar", "calcium fluoride"],
    "gallium": ["gallium", "gallium nitride", "gan power chips", "led chips", "gallium arsenide wafers", "gaas"],
    "indium": ["indium", "indium tin oxide", "ito coating", "touchscreen coating", "indium phosphide"],
    "lithium": ["lithium", "lithium carbonate", "lithium hydroxide", "lithium-ion battery cells", "li-ion battery", "battery grade lithium"],
    "magnesium-metal": ["magnesium", "magnesium metal", "magnesium alloy", "magnesium die casting", "aluminum alloy additive magnesium"],
    "nickel": ["nickel", "nickel sulfate", "nickel plating", "nickel alloy", "class 1 nickel", "stainless steel"],
    "niobium": ["niobium", "columbium", "ferroniobium", "hsla steel additive", "niobium superalloy"],
    "rare-earths": ["rare earth", "rare earths", "neodymium", "dysprosium", "ndfeb magnets", "neodymium magnets", "permanent magnets", "praseodymium", "rare earth magnets"],
    "tantalum": ["tantalum", "tantalum capacitors", "tantalum powder", "coltan"],
    "tin": ["tin", "refined tin", "solder", "tin plate", "tinplate"],
    "vanadium": ["vanadium", "ferrovanadium", "vanadium redox battery", "vanadium steel additive"],
    "zinc": ["zinc", "galvanizing", "galvanized steel zinc", "zinc die casting", "zinc ingots"],
    "zirconium-hafnium": ["zirconium", "hafnium", "zircon", "zirconium alloy", "nuclear fuel cladding", "hafnium oxide"],
    "antimony": ["antimony", "antimony trioxide", "antimony flame retardant", "antimonial lead"],
    "germanium": ["germanium", "germanium dioxide", "germanium optics", "infrared optics", "fiber optic germanium"],
    "graphite": ["graphite", "natural graphite", "synthetic graphite", "graphite anode", "battery anode", "spherical graphite", "graphite electrode"],
    "tellurium": ["tellurium", "cadmium telluride", "cdte", "bismuth telluride"],
    "tungsten": ["tungsten", "tungsten carbide", "cemented carbide", "wolfram", "tungsten heavy alloy"],
}

# Processing-stage data lives in data/processing_stage.json (source, page, year, grade for every entry). Without an entry a material
# uses its production shares and grade C. An entry with "shares" (every printed country share) gives a real HHI; with only
# "share" (top supplier) the HHI is a lower bound.
def load_processing():
    f = ROOT / _args.processing
    out = {}
    for mid, e in json.loads(f.read_text())["entries"].items():
        for k in ("country", "share", "basis", "source", "grade", "data_year", "url"):
            assert e.get(k) not in (None, ""), f"processing entry {mid} is missing {k}"
        assert 0 < float(e["share"]) <= 100, f"processing entry {mid}: share out of range"
        assert e["grade"] in ("A", "B", "C"), f"processing entry {mid}: grade"
        if "shares" in e:
            tot = sum(float(v) for v in e["shares"].values())
            assert tot <= 100.5, f"processing entry {mid}: shares add to {tot}"
            assert max(float(v) for v in e["shares"].values()) == float(e["share"]), f"processing entry {mid}: share must equal the largest listed share"
        out[mid] = e
    return out
PROCESSING = load_processing()


def load_expert_d():
    f = ROOT / _args.expert_d
    return json.loads(f.read_text())["materials"] if f.exists() else {}
EXPERT_D = load_expert_d()
DOUBLE_ENTRY = SRC.get("double_entry", {})

REGION_OF = {}
for c in ["China"]:
    REGION_OF[c] = "CN"
for c in ["Japan", "South Korea", "India", "Malaysia", "Indonesia", "Philippines", "Vietnam", "Thailand", "Taiwan", "Burma",
          "Laos", "Mongolia", "Australia", "Papua New Guinea", "New Caledonia", "Pakistan"]:
    REGION_OF[c] = "APAC"
for c in ["Norway", "Finland", "Germany", "Belgium", "Austria", "Estonia", "Spain", "Sweden", "France", "Greece", "Portugal",
          "Bulgaria"]:
    REGION_OF[c] = "EU"
for c in ["United States", "Canada", "Mexico"]:
    REGION_OF[c] = "NA"
for c in ["Brazil", "Argentina", "Chile", "Peru", "Bolivia", "Jamaica", "Guyana", "DR Congo", "South Africa", "Morocco",
          "Madagascar", "Senegal", "Sierra Leone", "Zimbabwe", "Mozambique", "Nigeria", "Rwanda", "Burundi", "Kenya", "Cuba",
          "Uzbekistan", "Kazakhstan", "Russia", "Turkey", "Iran", "Saudi Arabia", "Israel", "Guinea"]:
    REGION_OF[c] = "OTHER"
REGION_NAMES = {
    "CN": "China", "APAC": "Other Asia-Pacific", "EU": "Europe", "NA": "North America (incl. domestic)",
    "OTHER": "Other regions (Africa, Latin America, Middle East, Russia, Central Asia, Turkey)",
}

def hhi(shares):
    return sum(s * s for s in shares)

def main():
    mats = []
    for mid, (name, group) in NAMES.items():
        if mid not in SRC["import"]:
            continue
        imp = SRC["import"][mid]
        imp_sh = [{"country": cname(k), "share": float(v)} for k, v in imp["shares"].items()]
        imp_sh.sort(key=lambda x: -x["share"])
        imp_other = round(max(0.0, 100.0 - sum(x["share"] for x in imp_sh)), 1)
        prod = SRC["production"][mid]
        tot = float(sum(prod.values()))
        prod_sh = [{"country": cname(k), "share": round(100 * v / tot, 3)} for k, v in prod.items() if k != "Other"]
        prod_sh.sort(key=lambda x: -x["share"])
        prod_other = round(100 * prod.get("Other", 0) / tot, 3)
        raw_hhi = round(hhi([x["share"] for x in prod_sh]), 1)
        imp_hhi = round(hhi([x["share"] for x in imp_sh]), 1)
        dom = prod_sh[0]["country"]
        proc = PROCESSING.get(mid)
        if proc:
            if proc.get("shares"):
                proc_hhi = hhi([float(v) for v in proc["shares"].values()])
                hhi_note = "Every printed country share is used, so the HHI is a lower bound only for the unnamed remainder."
            else:
                proc_hhi = proc["share"] ** 2
                hhi_note = "Only the top supplier's share is printed, so the HHI is a lower bound."
            proc_info = {"grade": proc["grade"], "basis": "real", "country": proc["country"], "top_share": proc["share"],
                         "note": proc["basis"] + ". " + hhi_note,
                         "source": proc["source"], "data_year": proc["data_year"]}
        else:
            proc_hhi = raw_hhi
            proc_info = {"grade": "C", "basis": "mining_proxy", "country": dom, "top_share": prod_sh[0]["share"],
                         "note": "No processing-stage shares loaded. Production shares stand in for both terms of P (spec 4.8, grade C: Indicative).",
                         "source": f"USGS MCS {ED['mcs_edition']}, world production table", "data_year": ED["production_year"]}
        alts = []
        for x in prod_sh[1:]:
            alts.append({"country": x["country"], "global_share": round(x["share"], 2),
                         "capacity_status": "commercial", "qualification_status": "provisional",
                         "included_in_n_alt": True})
        mats.append({
            "id": mid, "name": name, "group": group, "synonyms": SYN[mid], "trade_codes": [],
            "dominant_country": dom, "dominant_import_country": imp_sh[0]["country"],
            "import": {"form": imp["form"], "period": ED["import_period"], "shares": imp_sh, "other_share": imp_other,
                       "hhi": imp_hhi, "grade": "B", "data_year": ED["import_year"]},
            "production": {"year": ED["production_year"], "shares": prod_sh, "other_share": prod_other, "hhi": raw_hhi, "grade": "B",
                           "data_year": ED["production_year"]},
            "raw_hhi_baseline": raw_hhi, "processing_hhi_baseline": round(proc_hhi, 1), "processing": proc_info,
            "nir": SRC["nir"][mid],
            "alternative_sources": alts,
            "substitution_difficulty": EXPERT_D[mid]["d"] if mid in EXPERT_D else 1.0,
            "d_status": "expert_reviewed" if mid in EXPERT_D else "estimated",
            **({"d_review": {k: EXPERT_D[mid][k] for k in ("n_experts", "min", "max", "disagreement", "reviewed")}} if mid in EXPERT_D else {}),
            "evidence": [
                {"kind": "usgs", "label": f"USGS Mineral Commodity Summaries {ED['mcs_edition']}, {name}",
                 "url": f"https://pubs.usgs.gov/periodicals/mcs{ED['mcs_edition']}/mcs{ED['mcs_edition']}-{mid}.pdf",
                 "tables": "Salient Statistics (import sources, net import reliance); World Production table"},
            ] + ([{"kind": "iea", "label": proc["source"],
                   "url": proc["url"], "tables": "Processing share text"}] if proc else []),
            "transcription": "double_entry" if mid in DOUBLE_ENTRY else "unverified",
            "review": {"signed_off_by": None, "signed_off_at": None},
            "taxonomy_note": "Net import reliance is shown for context only and is not a scoring input.",
        })
    out = {"taxonomy_version": "2026.11-preview.1", "formula_version": "1.1", "source_vintage": f"USGS MCS {ED['mcs_edition']}",
           "source_note": SRC["transcription_note"], "materials": mats}
    (ROOT / _args.out).write_text(json.dumps(out, indent=1))

    rcm = {"region_names": REGION_NAMES, "countries": [{"country": c, "region_code": r, "region_name": REGION_NAMES[r]}
                                                        for c, r in sorted(REGION_OF.items())]}
    (ROOT / "data" / "region_country_map.json").write_text(json.dumps(rcm, indent=1))
    missing = {x["country"] for m in mats for x in m["production"]["shares"] + m["import"]["shares"]} - set(REGION_OF)
    assert not missing, f"Add these countries to REGION_OF in scripts/build_taxonomy.py: {sorted(missing)}"
    print("materials", len(mats), "countries", len(REGION_OF))

if __name__ == "__main__":
    main()
