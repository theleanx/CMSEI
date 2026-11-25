"""Company layer glue. Scores come from published snapshots; the uploaded parts list is held in memory for one request and never stored.
The only thing that can be kept is an anonymous benchmark row (sector and rounded score) when the user ticks the box."""
from __future__ import annotations
import csv
import datetime as dt
import io
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .. import models as M
from ..config import settings
from ..engine import bom, compliance, simulator, taxonomy, scoring as sc
from . import snapshots as S

BENCH_MIN_N = 10
CUT_OPTIONS = ("partial", "full")


def score_map(db: Session) -> tuple[dict, dict]:
    scores, snaps = {}, {}
    for mid, m in taxonomy.MATERIALS.items():
        sn = S.latest(db, mid)
        if not sn:
            continue
        scores[mid] = {"name": m["name"], "score": sc.round_score(sn.composite), "composite": sn.composite, "tier": sn.tier,
                       "dominant_country": m["dominant_country"], "dominant_import_country": m["dominant_import_country"],
                       "indicative": sn.grade in ("C", "none")}
        snaps[mid] = sn
    return scores, snaps


def run(db: Session, raw: bytes | str, flags: dict | None = None, scenario: dict | None = None) -> dict:
    """Parse, analyse, screen for compliance, and (optionally) run one what-if. Raises bom.BomError on a bad file."""
    parsed = bom.parse(raw)
    rows = parsed["rows"]
    scores, snaps = score_map(db)
    for r in rows:
        r["minerals"] = [m for m in r["minerals"] if m in scores]
    res = bom.analyze(rows, scores)
    res["columns_found"], res["warnings"] = parsed["columns_found"], parsed["warnings"]
    res["compliance"] = compliance.report(rows, flags)
    res["snapshot_ids"] = {m: s.id for m, s in snaps.items() if any(m in r["minerals"] for r in rows)}
    res["indicative_materials"] = [scores[m["id"]]["name"] for m in res["materials"] if scores[m["id"]]["indicative"]]
    res["as_of"] = taxonomy.SOURCE_VINTAGE
    res["scenario"] = None
    if scenario and scenario.get("material_id"):
        mid = scenario["material_id"]
        if mid not in snaps:
            raise bom.BomError("Unknown material for the what-if.")
        cut = scenario.get("cut") if scenario.get("cut") in CUT_OPTIONS else "full"
        sn = snaps[mid]
        sim = simulator.simulate(sn.payload["inputs"], sn.payload["event_stages"], "supply_cut", cut)
        res["scenario"] = bom.scenario(rows, scores, mid, sim, scenario.get("country") or None, scenario.get("price_shock_pct"))
        res["scenario"]["cut"] = cut
        res["scenario"]["material_name"] = scores[mid]["name"]
    res["_rows"] = rows          # in-memory only, for the CSV and questionnaire builders. Removed before any JSON response.
    return res


def public(res: dict) -> dict:
    return {k: v for k, v in res.items() if not k.startswith("_")}


def parts_csv(res: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["product", "part_number", "supplier", "driver_material", "market_score", "tier", "annual_spend", "declared_origin", "origin_flag", "matched_by"])
    for p in res["parts"]:
        w.writerow([bom.safe_cell(x) for x in (p["product"], p["part"], p["supplier"], p["driver"], p["score"], p["tier"],
                                               "" if p["spend"] is None else f"{p['spend']:.2f}", p["origin"] or "", p["origin_flag"], p["matched_by"])])
    return out.getvalue()


def questionnaire_csv(res: dict, scores: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(bom.QUESTIONNAIRE_HEADER)
    for row in bom.questionnaire(res["_rows"], scores):
        w.writerow([bom.safe_cell(x) for x in row])
    return out.getvalue()


def template_csv() -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(bom.TEMPLATE_HEADER)
    w.writerows(bom.TEMPLATE_ROWS)
    return out.getvalue()


# ---------------------------------------------------------------- benchmark (opt-in, anonymous, k-anonymous on read)
SECTORS = {s["id"]: s["name"] for s in taxonomy.SECTORS["sectors"]}


def bench_add(db: Session, sector: str, score: int) -> bool:
    if sector not in SECTORS or not (0 <= score <= 100):
        return False
    today = dt.datetime.combine(dt.date.today(), dt.time.min)
    n = db.execute(select(func.count()).select_from(M.BenchmarkSubmission).where(M.BenchmarkSubmission.created_at >= today)).scalar() or 0
    if n >= settings.max_benchmark_per_day:
        return False
    db.add(M.BenchmarkSubmission(sector=sector, score=int(score)))
    db.commit()
    return True


def bench_read(db: Session, sector: str, score: int) -> dict:
    """Percentile of `score` among self-reported results for the sector. Nothing is shown below BENCH_MIN_N submissions."""
    vals = [r[0] for r in db.execute(select(M.BenchmarkSubmission.score).where(M.BenchmarkSubmission.sector == sector)).all()]
    if len(vals) < BENCH_MIN_N:
        return {"available": False, "n": len(vals), "needed": BENCH_MIN_N}
    below = sum(1 for v in vals if v < score)
    return {"available": True, "n": len(vals), "percentile": round(100 * below / len(vals)),
            "note": "Self-reported by users who chose to share. Not audited and not a random sample."}
