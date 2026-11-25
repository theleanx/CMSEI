"""Event gate (Full specification section 4.9), ported from the reference implementation in event-layer-test/eventgate.py.
The extractor is untrusted; everything here is deterministic.

The gate sits between an AI extractor and the score. The extractor is untrusted.
Everything here is deterministic code: schema check, source allowlist, validators,
sourcing rules, supersession, decay, caps and the human hold.

Standard library only. Python 3.9+.
"""
import re
import json
import hashlib
import unicodedata
import datetime as dt
from collections import defaultdict

# ---------------------------------------------------------------- parameters
EFFECT = {"statement": 0.02, "proposed": 0.08, "enacted": 0.15, "ban": 0.30}
RANK = {"statement": 1, "proposed": 2, "enacted": 3, "ban": 4}
G_CAP = 1.5
RUN_POINT_CAP = 10.0          # FS 4.9 item 7
DECAY_DAYS = {"statement": 30, "proposed": 60}   # FS 4.9 item 6
REVERIFY_DAYS = 30
HOLD_EXPIRY_HOURS = 72
HOLD_ALERT_COUNT = 5
FRESH_DAYS = 60               # TEST PARAMETER: the spec does not fix a document-age window
MAX_QUOTE_CHARS = 400         # TEST PARAMETER: schema length cap
TIERS = [(30, "Low"), (60, "Moderate"), (80, "High"), (100, "Critical")]

# Allowlist, materials and countries come from the repository data files (versioned; changes go through a pull request).
from ..engine import taxonomy as _tax
ALLOWLIST = {h: (v["tier"], v["issuer"]) for h, v in _tax.ALLOWLIST["hosts"].items()}

# Pattern per tracked material id. Plain words a document would use.
MATERIALS = {
    "arsenic": [r"arsenic"], "barite": [r"barite", r"baryte"], "bauxite": [r"bauxite"], "bismuth": [r"bismuth"],
    "chromium": [r"chromium", r"chromite", r"ferrochrome"], "cobalt": [r"cobalt"], "fluorspar": [r"fluorspar", r"fluorite"],
    "gallium": [r"gallium"], "indium": [r"indium"], "lithium": [r"lithium"], "magnesium-metal": [r"magnesium"],
    "nickel": [r"nickel"], "niobium": [r"niobium", r"columbium"], "rare-earths": [r"rare[- ]earths?"], "tantalum": [r"tantalum"],
    "tin": [r"tin"], "vanadium": [r"vanadium"], "zinc": [r"zinc"], "zirconium-hafnium": [r"zirconium", r"hafnium"],
}
COUNTRIES = {
    "China": [r"china", r"chinese"], "United States": [r"united states", r"u\.s\.", r"american"],
    "European Union": [r"european union", r"\beu\b", r"european commission"], "Indonesia": [r"indonesia\w*"],
    "DR Congo": [r"congo\w*", r"\bdrc\b"], "Australia": [r"australia\w*"], "Chile": [r"chile\w*"], "Russia": [r"russia\w*"],
    "Japan": [r"japan\w*"], "India": [r"india\w*"], "Brazil": [r"brazil\w*"], "Peru": [r"peru\w*"], "South Africa": [r"south africa\w*"],
    "Canada": [r"canad\w*"], "Malaysia": [r"malaysia\w*"], "Vietnam": [r"vietnam\w*"], "Philippines": [r"philippine\w*"],
    "Kazakhstan": [r"kazakhstan"], "Mexico": [r"mexic\w*"], "Turkey": [r"turkey", r"turkish", r"t\u00fcrkiye"], "Guinea": [r"guinea"],
    "Burma": [r"burma", r"myanmar"], "Zimbabwe": [r"zimbabwe\w*"], "Argentina": [r"argentin\w*"], "South Korea": [r"south korea\w*", r"korea\b"],
}
INSTRUMENTS = ["licence", "ban", "quota", "tax"]
STAGES = ["statement", "proposed", "enacted", "ban", "withdrawn"]
EVENT_TYPES = ["restriction", "withdrawal"]
FIELDS = ["doc_id", "event_type", "country", "material", "instrument", "stage",
          "effective_date", "quote"]

# Stage keyword sets (FS 4.9 item 4: "instrument and stage match a keyword set").
CUE = {
    "enacted": r"\b(shall|with effect from|takes? effect|came into (?:force|effect)|comes? into (?:force|effect)|"
               r"has decided to|decides? to|is imposing|imposed|imposes|introduced|introduces|starting|effective from|"
               r"will require|requires? exporters)\b",
    "ban": r"\b(bans?|banned|prohibit\w*)\b",
    "proposed": r"\b(draft|proposed|proposal|would|plans? to|seeks? to|consultation)\b",
    "statement": r"\b(warn\w*|signal\w*|consider\w*|review\w*|could|may|might|indicat\w*|hint\w*)\b",
    "withdrawn": r"\b(suspend\w*|lift\w*|revok\w*|rescind\w*|withdr\w*|repeal\w*)\b",
}
HEDGE = r"\b(draft|proposed|proposal|would|could|may|might|plans? to|considering|reviewing|warn\w*|signal\w*)\b"
INSTR_CUE = {
    "licence": r"\blicen[cs]\w*|\bpermit\w*|\bcontrols?\b|\bcurbs?\b|\brestrict\w*|\brequire\w*",
    "ban": r"\b(bans?|banned|prohibit\w*)\b",
    "quota": r"\bquotas?\b",
    "tax": r"\b(tax|duty|duties|levy)\b",
}
# Proposed hardening, NOT in the specification. Evaluated separately in the test.
H1_NEGATION = (r"\b(no plans|not plan\w*|not intend\w*|will not|won't|denied|denies|rules? out|ruled out|"
               r"cannot be ruled out|unlikely|analysts?|op-ed|argues?|if )\b")
HISTORY_DAYS = 90


# ---------------------------------------------------------------- text helpers
def norm(s):
    """NFKC, drop invisible format characters, collapse whitespace."""
    s = unicodedata.normalize("NFKC", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
    return re.sub(r"\s+", " ", s).strip()


def alias_present(patterns, text):
    t = text.lower()
    return any(re.search(r"(?<![a-z])" + p + r"(?![a-z])", t) for p in patterns)


MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}


def find_dates(text):
    """All dates in ISO, 'D Month YYYY' or 'Month D, YYYY' form, returned as ISO strings."""
    out = set()
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        out.add(m.group(0))
    for m in re.finditer(r"\b(\d{1,2}) ([A-Z][a-z]+) (\d{4})\b", text):
        mo = MONTHS.get(m.group(2).lower())
        if mo:
            out.add("%s-%02d-%02d" % (m.group(3), mo, int(m.group(1))))
    for m in re.finditer(r"\b([A-Z][a-z]+) (\d{1,2}), (\d{4})\b", text):
        mo = MONTHS.get(m.group(1).lower())
        if mo:
            out.add("%s-%02d-%02d" % (m.group(3), mo, int(m.group(2))))
    return out


def d(s):
    return dt.date.fromisoformat(s)


def shingles(text, n=5):
    w = re.findall(r"[a-z0-9]+", text.lower())
    return {" ".join(w[i:i + n]) for i in range(max(1, len(w) - n + 1))}


def jaccard(a, b):
    return len(a & b) / max(1, len(a | b))


def tier_of(score):
    for hi, name in TIERS:
        if score <= hi:
            return name
    return "Critical"


# ---------------------------------------------------------------- stage 1: schema
def check_schema(c):
    """The extractor returns structured fields only. Unknown fields, long strings and
    values outside the enumerations are rejected; nothing free-form reaches the score."""
    r = []
    if not isinstance(c, dict):
        return ["S0_not_object"]
    if set(c.keys()) != set(FIELDS):
        extra = sorted(set(c.keys()) - set(FIELDS))
        miss = sorted(set(FIELDS) - set(c.keys()))
        if extra:
            r.append("S1_extra_fields:" + ",".join(extra))
        if miss:
            r.append("S1_missing_fields:" + ",".join(miss))
        return r
    for k in FIELDS:
        v = c[k]
        if k == "effective_date":
            if v is not None and not (isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)):
                r.append("S2_bad_date")
        elif not isinstance(v, str):
            r.append("S2_not_string:" + k)
    if r:
        return r
    if len(c["quote"]) > MAX_QUOTE_CHARS:
        r.append("S3_quote_too_long")
    if c["event_type"] not in EVENT_TYPES:
        r.append("S4_bad_event_type")
    if c["country"] not in COUNTRIES:
        r.append("S4_bad_country")
    if c["material"] not in MATERIALS:
        r.append("S4_untracked_material")
    if c["instrument"] not in INSTRUMENTS:
        r.append("S4_bad_instrument")
    if c["stage"] not in STAGES:
        r.append("S4_bad_stage")
    if c["event_type"] == "withdrawal" and c["stage"] != "withdrawn":
        r.append("S5_type_stage_mismatch")
    if c["event_type"] == "restriction" and c["stage"] == "withdrawn":
        r.append("S5_type_stage_mismatch")
    return r


# ---------------------------------------------------------------- stage 2: validators
def validate(c, doc, run_date, harden=False):
    """FS 4.9 item 4. Returns a list of failure codes; empty means all validators pass."""
    r = []
    host = doc.get("host", "")
    if host not in ALLOWLIST:                       # item 1, exact host match only
        return ["R1_not_allowlisted"]
    q, text = norm(c["quote"]), norm(doc["text"])
    if not q or q not in text:                      # V1 verbatim quote
        r.append("V1_quote_not_verbatim")
    try:                                            # V2 document date and country
        pub = d(doc["pub_date"])
        if pub > run_date:
            r.append("V2_future_date")
        elif (run_date - pub).days > FRESH_DAYS:
            r.append("V2_stale_document")
    except Exception:
        r.append("V2_bad_date")
    issuer = ALLOWLIST[host][1]
    # an official document speaks for its issuer even when it never writes the country's name
    # (a US agency notice rarely says "United States"); everything else must name the country
    if not (issuer == c["country"] or alias_present(COUNTRIES[c["country"]], text)):
        r.append("V2_country_not_in_document")
    if not alias_present(MATERIALS[c["material"]], q):   # V3 material maps to tracked category
        r.append("V3_material_not_in_quote")
    st = c["stage"]                                 # V4 stage and instrument keyword sets
    if not re.search(CUE[st], q, re.I):
        r.append("V4_stage_cue_missing")
    if st in ("enacted", "ban") and re.search(HEDGE, q, re.I):
        r.append("V4_hedge_in_firm_stage")
    if st == "enacted" and re.search(CUE["ban"], q, re.I) and c["instrument"] != "ban":
        pass  # a ban word beside a licence claim is allowed; the instrument cue decides
    if c["instrument"] in INSTR_CUE and not re.search(INSTR_CUE[c["instrument"]], q, re.I):
        r.append("V4_instrument_cue_missing")
    if c["effective_date"] is not None:             # V6 effective date appears in the document
        if c["effective_date"] not in find_dates(text):
            r.append("V6_effective_date_not_in_document")
    if harden:                                      # proposed additions, not in the specification
        if re.search(H1_NEGATION, q, re.I):
            r.append("H1_negation_or_hedge")
        if c["effective_date"] and st in ("enacted", "ban") and "pub" in locals():
            if (pub - d(c["effective_date"])).days > HISTORY_DAYS:
                r.append("H2_historical_effective_date")
        yrs = [int(y) for y in re.findall(r"\b(?:in|since|during) (20\d\d)\b", q, re.I)]
        if yrs and "pub" in locals() and min(yrs) < pub.year and st in ("enacted", "ban"):
            r.append("H2_historical_year_in_quote")
    return r


# ---------------------------------------------------------------- stage 3: sourcing rules
def independent_clusters(docs):
    """FS 4.9 item 2: one outlet alone never counts, and copies of one story count once."""
    clusters = []
    for dd in docs:
        sh = shingles(norm(dd["text"]))
        for cl in clusters:
            if dd["host"] == cl["host"] or jaccard(sh, cl["sh"]) >= 0.5:
                cl["docs"].append(dd)
                break
        else:
            clusters.append({"host": dd["host"], "sh": sh, "docs": [dd]})
    return clusters


def qualify(accepted, docs_by_id):
    """accepted: candidates that passed schema and validators.
    Returns {key: record} where key = (event_type, material, country, instrument, stage)."""
    groups = defaultdict(list)
    for c in accepted:
        groups[(c["event_type"], c["material"], c["country"], c["instrument"], c["stage"])].append(c)
    out = {}
    for key, cs in groups.items():
        et, mat, cty, ins, st = key
        docs = [docs_by_id[c["doc_id"]] for c in cs]
        tier1_issuer = [x for x in docs if ALLOWLIST[x["host"]][0] == 1 and ALLOWLIST[x["host"]][1] == cty]
        n_ind = len(independent_clusters(docs))
        if st in ("enacted", "ban") or (et == "withdrawal"):
            # enacted, ban: official text from the issuing government
            if st in ("enacted", "ban"):
                ok = bool(tier1_issuer)
                status = "qualified" if ok else "pending_official_text"
            else:
                ok = bool(tier1_issuer) or n_ind >= 2
                status = "qualified" if ok else "pending_corroboration"
        else:
            ok = n_ind >= 2
            status = "qualified" if ok else "pending_corroboration"
        eff = None
        for c in cs:
            if c["effective_date"]:
                eff = c["effective_date"]
        out[key] = {"key": key, "status": status, "n_independent": n_ind,
                    "effective_date": eff, "docs": [x["id"] for x in docs],
                    "tier1_issuer": bool(tier1_issuer), "quotes": [c["quote"] for c in cs]}
    return out


def run_gate(cands, docs_by_id, run_date, harden=False):
    """Full automated gate. Returns (records, qualified) where records has one row per candidate."""
    records, accepted = [], []
    for c in cands:
        reasons = check_schema(c)
        doc = docs_by_id.get(c.get("doc_id")) if isinstance(c, dict) else None
        if not reasons and doc is None:
            reasons = ["S6_unknown_document"]
        if not reasons:
            reasons = validate(c, doc, run_date, harden)
        records.append({"cand": c, "reasons": reasons})
        if not reasons:
            accepted.append(c)
    return records, qualify(accepted, docs_by_id)


