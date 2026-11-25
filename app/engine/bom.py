"""Bill-of-materials roll-up (company layer). Pure functions: no database, no storage, no network.

A company uploads a parts list. Each part is matched to the tracked materials it depends on, then the market-level
score of each material is rolled up to products and suppliers.

The roll-up is a screening heuristic and is NOT part of the validated index:
  part exposure     = the highest market score among the materials the part depends on
  product exposure  = the highest part exposure in the product ("peak"), shown with the share of spend in High or Critical parts
  supplier exposure = the same, over the parts a supplier delivers
Nothing here is stored. The caller holds the rows in memory for one request.
"""
from __future__ import annotations
import csv
import io
import re
from . import classifier, taxonomy

MAX_BYTES = 2_000_000
MAX_ROWS = 20_000
MAX_CELL = 200

ALIASES = {
    "product": {"product", "product_line", "assembly", "finished_good", "finished_goods", "top_level", "parent", "parent_material", "header_material"},
    "part": {"part", "part_number", "part_no", "part_id", "component", "component_number", "idnrk", "matnr", "material_number", "item", "sku"},
    "description": {"description", "desc", "maktx", "component_description", "part_description", "text", "material_description"},
    "supplier": {"supplier", "supplier_name", "vendor", "vendor_name", "lifnr", "name1", "manufacturer"},
    "minerals": {"mineral", "minerals", "critical_material", "critical_materials", "cmsei_material", "cmsei_materials", "material_id"},
    "spend": {"annual_spend", "spend", "annual_spend_usd", "spend_usd", "annual_value", "annual_cost", "value_usd"},
    "origin": {"origin_country", "country_of_origin", "coo", "herkl", "mining_country", "origin"},
    "processing": {"processing_country", "refining_country", "smelter_country", "processed_in"},
    "hts": {"hts", "hts_code", "hs_code", "commodity_code", "steuc"},
}
TEMPLATE_HEADER = ["product", "part_number", "description", "supplier", "minerals", "annual_spend_usd", "origin_country", "processing_country"]
TEMPLATE_ROWS = [
    ["Motor 3kW", "MTR-1001", "NdFeB magnet segment", "Acme Magnetics", "rare-earths", "120000", "", ""],
    ["Motor 3kW", "MTR-1002", "Winding wire", "Copperline", "", "45000", "", ""],
    ["Sensor board", "SNS-2001", "GaAs wafer die", "Waferworks", "gallium; arsenic", "80000", "China", ""],
    ["Sensor board", "SNS-2002", "Tantalum capacitor", "Capco", "tantalum", "30000", "Rwanda", "China"],
]

ISO2 = {"CN": "china", "PE": "peru", "ZA": "south africa", "CD": "democratic republic of the congo", "CG": "republic of the congo", "ID": "indonesia",
        "AU": "australia", "CL": "chile", "AR": "argentina", "BR": "brazil", "RU": "russia", "KZ": "kazakhstan", "MX": "mexico", "IN": "india",
        "MA": "morocco", "MY": "malaysia", "JP": "japan", "KR": "korea", "DE": "germany", "CA": "canada", "US": "united states", "TW": "taiwan",
        "VN": "vietnam", "TR": "turkey", "FI": "finland", "NO": "norway", "BE": "belgium", "EE": "estonia", "JM": "jamaica", "GY": "guyana",
        "RW": "rwanda", "UG": "uganda", "TZ": "tanzania", "ZM": "zambia", "AO": "angola", "BI": "burundi", "CF": "central african republic",
        "SS": "south sudan", "KP": "north korea", "IR": "iran", "PH": "philippines", "GN": "guinea", "MM": "myanmar", "BO": "bolivia", "NG": "nigeria"}
COUNTRY_ALIASES = {"drc": "democratic republic of the congo", "congo kinshasa": "democratic republic of the congo", "congo drc": "democratic republic of the congo",
                   "prc": "china", "peoples republic of china": "china", "usa": "united states", "us": "united states", "united states of america": "united states",
                   "republic of korea": "korea", "south korea": "korea", "dprk": "north korea", "russian federation": "russia", "viet nam": "vietnam",
                   "congo brazzaville": "republic of the congo", "car": "central african republic"}


def norm_country(x: str | None) -> str | None:
    """Lower-case canonical country key, or None for blank. Accepts names, ISO 3166 two-letter codes and a few common aliases."""
    if not x:
        return None
    t = re.sub(r"[^a-z ]", "", x.strip().lower().replace("-", " ").replace("_", " "))
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return None
    raw = x.strip()
    if len(raw) == 2 and raw.upper() in ISO2:
        return ISO2[raw.upper()]
    t = COUNTRY_ALIASES.get(t, t)
    return t.replace("southafrica", "south africa")


def _h(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.strip().lower()).strip("_")


def _clean(v) -> str:
    return re.sub(r"[\x00-\x1f]", " ", (v or "")).strip()[:MAX_CELL]


def safe_cell(v) -> str:
    """Spreadsheet formula injection guard for any CSV we hand back."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


class BomError(ValueError):
    pass


_NAME_INDEX = None


def _name_index() -> dict:
    global _NAME_INDEX
    if _NAME_INDEX is None:
        idx = {}
        for mid, m in taxonomy.MATERIALS.items():
            for k in [mid, m["name"]] + m["synonyms"]:
                idx.setdefault(_h(k), mid)
        _NAME_INDEX = idx
    return _NAME_INDEX


def resolve_minerals(minerals_cell: str, description: str, cache: dict) -> tuple[list[str], str]:
    """Material ids for one row and how they were found: 'listed', 'description' or 'none'."""
    ids = []
    if minerals_cell:
        for tok in re.split(r"[;|,/]+", minerals_cell):
            k = _h(tok)
            if not k:
                continue
            mid = _name_index().get(k)
            if mid is None:
                key = ("t", k)
                if key not in cache:
                    r = classifier.classify(tok, None, None)
                    cache[key] = r["resolved"]
                mid = cache[key]
            if mid and mid not in ids:
                ids.append(mid)
        if ids:
            return ids, "listed"
    if description:
        key = ("d", description.lower())
        if key not in cache:
            cache[key] = classifier.classify(description, None, None)["resolved"]
        if cache[key]:
            return [cache[key]], "description"
    return [], "none"


def _to_float(v: str) -> float | None:
    if not v:
        return None
    s = re.sub(r"[,$\s]", "", v)
    try:
        x = float(s)
    except ValueError:
        return None
    return x if 0 <= x < 1e12 else None


def parse(raw: bytes | str) -> dict:
    """CSV text -> {rows, columns_found, warnings}. Raises BomError with a plain message the user can act on."""
    if isinstance(raw, bytes):
        if len(raw) > MAX_BYTES:
            raise BomError(f"The file is larger than {MAX_BYTES // 1_000_000} MB. Split it or remove columns you do not need.")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
    else:
        text = raw
        if len(text.encode("utf-8", "ignore")) > MAX_BYTES:
            raise BomError(f"The data is larger than {MAX_BYTES // 1_000_000} MB.")
    if not text.strip():
        raise BomError("The file is empty.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rdr = csv.reader(io.StringIO(text), dialect)
    try:
        header = next(rdr)
    except StopIteration:
        raise BomError("The file has no header row.")
    cols = {}
    for i, h in enumerate(header):
        k = _h(h)
        for field, names in ALIASES.items():
            if k in names and field not in cols:
                cols[field] = i
    if "part" not in cols:
        raise BomError("No part column found. Name one column part_number (SAP: MATNR or IDNRK). Download the template to see the layout.")
    if "minerals" not in cols and "description" not in cols:
        raise BomError("Need a minerals column (for example rare-earths; gallium) or a description column so parts can be matched to materials.")
    rows, warnings, cache = [], [], {}
    for n, rec in enumerate(rdr, start=2):
        if not any(c.strip() for c in rec):
            continue
        if len(rows) >= MAX_ROWS:
            raise BomError(f"More than {MAX_ROWS:,} rows. Split the file by product family.")
        g = lambda f: _clean(rec[cols[f]]) if f in cols and cols[f] < len(rec) else ""
        ids, how = resolve_minerals(g("minerals"), g("description"), cache)
        spend_raw = g("spend")
        spend = _to_float(spend_raw)
        if spend_raw and spend is None:
            warnings.append(f"Row {n}: spend is not a number and was ignored.")
        rows.append({"row": n, "product": g("product") or "(no product)", "part": g("part") or f"(row {n})", "supplier": g("supplier") or "(no supplier)",
                     "minerals": ids, "matched_by": how, "spend": spend, "origin": g("origin") or None, "processing": g("processing") or None,
                     "hts": g("hts") or None})
    if not rows:
        raise BomError("The file has a header but no data rows.")
    return {"rows": rows, "columns_found": sorted(cols), "warnings": warnings[:20]}


# ------------------------------------------------------------------ analysis
def _tier_hi(tier: str) -> bool:
    return tier in ("High", "Critical")


def origin_flag(origin: str | None, mat: dict) -> str:
    """declared_dominant | declared_other | undeclared, against the material's dominant producer and dominant US import source."""
    c = norm_country(origin)
    if not c:
        return "undeclared"
    dom = {norm_country(mat.get("dominant_country")), norm_country(mat.get("dominant_import_country"))} - {None}
    return "declared_dominant" if c in dom else "declared_other"


def analyze(rows: list[dict], scores: dict, top: int = 25) -> dict:
    """`scores` maps material id -> {name, score (int), composite (float), tier, dominant_country, dominant_import_country}."""
    mapped = [r for r in rows if r["minerals"]]
    unmapped = [r for r in rows if not r["minerals"]]
    spend_total = sum(r["spend"] or 0.0 for r in rows)
    spend_mapped = sum(r["spend"] or 0.0 for r in mapped)

    def part_exposure(r):
        best = max(r["minerals"], key=lambda m: scores[m]["composite"])
        return best, scores[best]

    parts = []
    for r in mapped:
        best, s = part_exposure(r)
        parts.append({"row": r["row"], "product": r["product"], "part": r["part"], "supplier": r["supplier"], "spend": r["spend"],
                      "minerals": r["minerals"], "driver": best, "score": s["score"], "tier": s["tier"],
                      "origin": r["origin"], "origin_flag": origin_flag(r["origin"], taxonomy.MATERIALS[best]), "matched_by": r["matched_by"]})

    def roll(key):
        groups = {}
        for p in parts:
            groups.setdefault(p[key], []).append(p)
        total_parts = {}
        for r in rows:
            total_parts[r[key]] = total_parts.get(r[key], 0) + 1
        out = []
        for name, ps in groups.items():
            peak = max(ps, key=lambda p: (scores[p["driver"]]["composite"], p["part"]))
            sp = sum(p["spend"] or 0.0 for p in ps)
            sp_hi = sum(p["spend"] or 0.0 for p in ps if _tier_hi(p["tier"]))
            mats = sorted({m for p in ps for m in p["minerals"]}, key=lambda m: -scores[m]["composite"])
            out.append({"name": name, "score": peak["score"], "tier": peak["tier"], "driver": peak["driver"], "driver_name": scores[peak["driver"]]["name"],
                        "dependent_parts": len(ps), "total_parts": total_parts[name], "spend": sp,
                        "spend_high_share": (sp_hi / sp) if sp > 0 else None, "materials": mats,
                        "high_parts": sum(1 for p in ps if _tier_hi(p["tier"]))})
        out.sort(key=lambda x: (-x["score"], -x["high_parts"], x["name"]))
        return out

    mats = {}
    for p in parts:
        for m in p["minerals"]:
            e = mats.setdefault(m, {"id": m, "name": scores[m]["name"], "score": scores[m]["score"], "tier": scores[m]["tier"], "parts": 0, "spend": 0.0,
                                     "declared_dominant": 0, "declared_other": 0, "undeclared": 0})
            e["parts"] += 1
            e["spend"] += p["spend"] or 0.0
            e[origin_flag(p["origin"], taxonomy.MATERIALS[m])] += 1
    materials = sorted(mats.values(), key=lambda e: (-scores[e["id"]]["composite"], e["name"]))
    products, suppliers = roll("product"), roll("supplier")
    n_origin = {k: sum(1 for p in parts if p["origin_flag"] == k) for k in ("declared_dominant", "declared_other", "undeclared")}
    high_spend = sum(p["spend"] or 0.0 for p in parts if _tier_hi(p["tier"]))
    top_sup_share = None
    if high_spend > 0:
        by_sup = {}
        for p in parts:
            if _tier_hi(p["tier"]):
                by_sup[p["supplier"]] = by_sup.get(p["supplier"], 0.0) + (p["spend"] or 0.0)
        s, v = max(by_sup.items(), key=lambda kv: kv[1])
        top_sup_share = {"supplier": s, "share": v / high_spend}
    headline = None
    if products:
        p0 = products[0]
        headline = (f"{p0['name']}: {p0['dependent_parts']} of {p0['total_parts']} parts depend on tracked materials; "
                    f"the most exposed is {p0['driver_name']}. Exposure {p0['score']} ({p0['tier']}).")
    return {
        "summary": {"rows": len(rows), "mapped_rows": len(mapped), "unmapped_rows": len(unmapped), "products": len({r['product'] for r in rows}),
                    "suppliers": len({r['supplier'] for r in rows}), "spend_total": spend_total, "spend_mapped": spend_mapped,
                    "spend_high_or_critical": high_spend, "has_spend": spend_total > 0, "top_supplier_in_high_spend": top_sup_share,
                    "origin_declared": n_origin, "headline": headline},
        "products": products[:top * 4], "suppliers": suppliers[:top * 4], "materials": materials,
        "parts": sorted(parts, key=lambda p: (-scores[p["driver"]]["composite"], p["part"]))[:top * 8],
        "unmapped_sample": [u["part"] for u in unmapped[:25]],
        "method": "Screening roll-up: part = highest market score among its materials; product and supplier = highest part exposure. Not part of the validated index.",
    }


# ------------------------------------------------------------------ what-if
def scenario(rows: list[dict], scores: dict, material_id: str, sim: dict, country: str | None = None, price_shock_pct: float | None = None) -> dict:
    """Effect of a hypothetical supply cut on one material.
    `sim` is the simulator result for that material ({official:{composite,tier}, simulated:{composite,tier}}).
    A part is 'direct' if its declared origin matches `country`, 'unknown' if no origin is declared, 'other' if declared elsewhere.
    With no country, every part of the material is direct. Cost = spend x price shock, shown as a range and always labelled an assumption."""
    from . import scoring as sc
    target = norm_country(country) if country else None
    hit_rows = [r for r in rows if material_id in r["minerals"]]
    cls = {"direct": [], "unknown": [], "other": []}
    for r in hit_rows:
        c = norm_country(r["origin"])
        k = "direct" if target is None or c == target else ("unknown" if c is None else "other")
        cls[k].append(r)
    sp = {k: sum(r["spend"] or 0.0 for r in v) for k, v in cls.items()}
    before_s, after_s = sim["official"]["composite"], sim["simulated"]["composite"]
    new_scores = dict(scores)
    new_scores[material_id] = dict(scores[material_id], composite=after_s, score=sc.round_score(after_s), tier=sim["simulated"]["tier"])
    base = analyze(rows, scores, top=1000)
    after = analyze(rows, new_scores, top=1000)
    after_by = {p["name"]: p for p in after["products"]}
    hit_products = []
    names = {r["product"] for r in hit_rows}
    for p in base["products"]:
        if p["name"] in names:
            a = after_by[p["name"]]
            n_direct = sum(1 for r in cls["direct"] if r["product"] == p["name"])
            n_unknown = sum(1 for r in cls["unknown"] if r["product"] == p["name"])
            hit_products.append({"name": p["name"], "parts_direct": n_direct, "parts_unknown_origin": n_unknown,
                                 "score_before": p["score"], "tier_before": p["tier"], "score_after": a["score"], "tier_after": a["tier"]})
    cost = None
    if price_shock_pct is not None and price_shock_pct >= 0:
        low, high = sp["direct"] * price_shock_pct / 100.0, (sp["direct"] + sp["unknown"]) * price_shock_pct / 100.0
        cost = {"price_shock_pct": price_shock_pct, "low": low, "high": high,
                "note": "Your own assumption times annual spend on affected parts. The platform has no price data and does not forecast prices."}
    return {"material": material_id, "country": country, "market_before": {"score": sc.round_score(before_s), "tier": sim["official"]["tier"]},
            "market_after": {"score": sc.round_score(after_s), "tier": sim["simulated"]["tier"]},
            "parts": {k: len(v) for k, v in cls.items()}, "spend": sp, "has_spend": any(r["spend"] for r in hit_rows),
            "products_hit": hit_products, "cost": cost,
            "note": "Hypothetical. The market-level change comes from the CMSEI simulator, whose mapping from supply cut to event stage is an unvalidated modeling choice. "
                    "Direct versus unknown depends on origin countries your suppliers declared."}


# ------------------------------------------------------------------ supplier questionnaire
QUESTIONNAIRE_HEADER = ["supplier", "part_number", "description_asked_about", "material", "origin_country", "processing_country", "smelter_or_refiner_name",
                        "responsible_sourcing_audit_status", "alternate_source_available", "contact_name", "answered_on"]


def questionnaire(rows: list[dict], scores: dict) -> list[list[str]]:
    """One line per supplier part that depends on a tracked material, with blank answer columns for the supplier.
    Answers come back as origin_country and processing_country columns that can be pasted into the BOM file."""
    out = []
    for r in sorted((r for r in rows if r["minerals"]), key=lambda r: (r["supplier"], r["part"])):
        for m in r["minerals"]:
            out.append([r["supplier"], r["part"], "", scores[m]["name"], r["origin"] or "", r["processing"] or "", "", "", "", "", ""])
    return out
