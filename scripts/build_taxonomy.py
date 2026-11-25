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
SRC = json.loads((ROOT / "data" / "source_mcs2024.json").read_text())

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
}

# Real processing-stage shares (IEA Critical Minerals Market Review 2023). Top supplier only, so a lower bound.
PROCESSING = {
    "cobalt": dict(country="China", share=75.0, basis="over 75% of refined cobalt output, 2022",
                   source="IEA, Critical Minerals Market Review 2023 (July 2023), p. 57", grade="B"),
    "rare-earths": dict(country="China", share=90.0, basis="90% of processing, 2022 into 2023",
                        source="IEA, Critical Minerals Market Review 2023 (July 2023), p. 59", grade="B"),
}

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
            proc_hhi = proc["share"] ** 2
            proc_info = {"grade": proc["grade"], "basis": "real", "country": proc["country"], "top_share": proc["share"],
                         "note": proc["basis"] + ". Only the top supplier's share is printed, so the HHI is a lower bound.",
                         "source": proc["source"], "data_year": 2022}
        else:
            proc_hhi = raw_hhi
            proc_info = {"grade": "C", "basis": "mining_proxy", "country": dom, "top_share": prod_sh[0]["share"],
                         "note": "No processing-stage shares loaded. Production shares stand in for both terms of P (spec 4.8, grade C: Indicative).",
                         "source": "USGS MCS 2024, world production table", "data_year": 2023}
        alts = []
        for x in prod_sh[1:]:
            alts.append({"country": x["country"], "global_share": round(x["share"], 2),
                         "capacity_status": "commercial", "qualification_status": "provisional",
                         "included_in_n_alt": True})
        mats.append({
            "id": mid, "name": name, "group": group, "synonyms": SYN[mid], "trade_codes": [],
            "dominant_country": dom, "dominant_import_country": imp_sh[0]["country"],
            "import": {"form": imp["form"], "period": "2019-22", "shares": imp_sh, "other_share": imp_other,
                       "hhi": imp_hhi, "grade": "B", "data_year": 2022},
            "production": {"year": 2023, "shares": prod_sh, "other_share": prod_other, "hhi": raw_hhi, "grade": "B",
                           "data_year": 2023},
            "raw_hhi_baseline": raw_hhi, "processing_hhi_baseline": round(proc_hhi, 1), "processing": proc_info,
            "nir": SRC["nir"][mid],
            "alternative_sources": alts,
            "substitution_difficulty": 1.0, "d_status": "estimated",
            "evidence": [
                {"kind": "usgs", "label": f"USGS Mineral Commodity Summaries 2024, {name}",
                 "url": f"https://pubs.usgs.gov/periodicals/mcs2024/mcs2024-{mid}.pdf",
                 "tables": "Salient Statistics (import sources, net import reliance); World Production table"},
            ] + ([{"kind": "iea", "label": proc["source"],
                   "url": "https://iea.blob.core.windows.net/assets/afc35261-41b2-47d4-86d6-d5d77fc259be/CriticalMineralsMarketReview2023.pdf",
                   "tables": "Processing share text"}] if proc else []),
            "transcription": "unverified",
            "review": {"signed_off_by": None, "signed_off_at": None},
            "taxonomy_note": "Net import reliance is shown for context only and is not a scoring input.",
        })
    out = {"taxonomy_version": "2026.11-preview.1", "formula_version": "1.1", "source_vintage": "USGS MCS 2024",
           "source_note": SRC["transcription_note"], "materials": mats}
    (ROOT / "data" / "material_categories.json").write_text(json.dumps(out, indent=1))

    rcm = {"region_names": REGION_NAMES, "countries": [{"country": c, "region_code": r, "region_name": REGION_NAMES[r]}
                                                        for c, r in sorted(REGION_OF.items())]}
    (ROOT / "data" / "region_country_map.json").write_text(json.dumps(rcm, indent=1))
    missing = {x["country"] for m in mats for x in m["production"]["shares"] + m["import"]["shares"]} - set(REGION_OF)
    assert not missing, missing
    print("materials", len(mats), "countries", len(REGION_OF))

if __name__ == "__main__":
    main()
