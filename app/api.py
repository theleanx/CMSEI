"""Public API v1. Read endpoints are open and rate limited. State-changing endpoints need X-Session-Token."""
from __future__ import annotations
import csv
import io
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session
from . import models as M
from .config import settings
from .db import get_db
from .engine import explain, recommend, simulator, taxonomy, scoring as sc
from .services import assess, sessions, snapshots as S, pdf

router = APIRouter(prefix="/api/v1")


class ApiError(HTTPException):
    def __init__(self, status, code, message):
        super().__init__(status_code=status, detail={"error": {"code": code, "message": message}})


# ---------- request models (strict, length-capped) ----------
class AssessIn(BaseModel):
    material_description: str | None = Field(default=None, max_length=300)
    material_id: str | None = Field(default=None, max_length=64)
    sourcing_region: str | None = Field(default=None, max_length=16)
    volume_tier: str | None = Field(default=None, max_length=16)

    @field_validator("sourcing_region")
    @classmethod
    def _r(cls, v):
        if v is not None and v not in recommend.REGION_KEYS:
            raise ValueError("unknown sourcing_region")
        return v

    @field_validator("volume_tier")
    @classmethod
    def _v(cls, v):
        if v is not None and v not in recommend.VOLUME_KEYS:
            raise ValueError("unknown volume_tier")
        return v


class ScenarioIn(BaseModel):
    material_id: str = Field(max_length=64)
    family: str = Field(max_length=32)
    option: str | None = Field(default=None, max_length=16)
    sourcing_region: str | None = Field(default=None, max_length=16)
    volume_tier: str | None = Field(default=None, max_length=16)


class WatchIn(BaseModel):
    material_id: str = Field(max_length=64)
    alert_threshold: float | None = Field(default=None, ge=0, le=100)


class CorrectionIn(BaseModel):
    material_id: str = Field(max_length=64)
    item: str = Field(min_length=2, max_length=128)
    proposed_value: str = Field(min_length=1, max_length=255)
    source_link: str = Field(min_length=8, max_length=512, pattern=r"^https?://")
    note: str = Field(default="", max_length=1000)


def session_hash(db: Session, token: str | None, required: bool = True):
    h = sessions.get(db, token)
    if required and not h:
        raise ApiError(401, "no_session", "Missing or expired X-Session-Token. Create one with POST /api/v1/sessions.")
    return h


def tok(x_session_token: str | None = Header(default=None)):
    return x_session_token


# ---------- status ----------
@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("select 1"))
        ok = True
    except Exception:
        ok = False
    return JSONResponse({"status": "ok" if ok else "degraded", "database": ok, "version": "1.0.0"}, status_code=200 if ok else 503)


def data_status(db: Session) -> dict:
    last = {}
    for job in ("publish", "monitor", "reverify", "housekeeping"):
        r = db.execute(select(M.JobRun).where(M.JobRun.job == job).order_by(M.JobRun.id.desc())).scalars().first()
        last[job] = None if not r else {"status": r.status, "started_at": r.started_at.isoformat() + "Z",
                                        "finished_at": r.finished_at.isoformat() + "Z" if r.finished_at else None, "detail": r.detail}
    held = db.execute(select(func.count()).select_from(M.EventRecord).where(M.EventRecord.status == "held")).scalar() or 0
    log = S.verify_chain(db)
    quarantined = db.execute(select(func.count()).select_from(M.QuarantinedDocument)).scalar() or 0
    snaps = db.execute(select(func.count()).select_from(M.ScoreSnapshot).where(M.ScoreSnapshot.superseded_at.is_(None))).scalar() or 0
    newest = db.execute(select(func.max(M.ScoreSnapshot.published_at))).scalar()
    feed_stale = True
    mon = last.get("monitor")
    if mon and mon["status"] == "ok":
        import datetime as dt
        fin = dt.datetime.fromisoformat(mon["finished_at"].rstrip("Z")) if mon["finished_at"] else None
        feed_stale = not fin or (M.now() - fin).days > settings.stale_days_events
    return {
        "launch_status": settings.launch_status, "event_layer": "published" if settings.publish_events else "shadow (computes events, publishes nothing)",
        "data_vintage": taxonomy.SOURCE_VINTAGE, "taxonomy_version": taxonomy.TAXONOMY_VERSION, "formula_version": sc.FORMULA_VERSION,
        "snapshot_log": log, "published_snapshots": snaps, "newest_snapshot_at": newest.isoformat() + "Z" if newest else None,
        "quarantined_documents": quarantined, "held_events": held, "held_alert": held > 5, "event_feed_stale": feed_stale, "jobs": last,
        "maintainer": {"name": settings.maintainer_name, "role": settings.maintainer_role},
        "second_reviewer": {"name": settings.reviewer_name, "role": settings.reviewer_role}, "verification": S.verification_status(db),
        "transcription": "USGS figures were read through a page reader and have not been checked against the PDFs by a person.",
        "caps": {"claude_daily_calls": settings.claude_daily_call_cap, "claude_monthly_calls": settings.claude_monthly_call_cap},
    }


@router.get("/data-status")
def data_status_ep(db: Session = Depends(get_db)):
    return data_status(db)


@router.get("/methodology")
def methodology():
    return {
        "name": "Critical Material Supply Exposure Index (CMSEI)", "built_on": "Material Supply Exposure Index", "formula_version": sc.FORMULA_VERSION, "scope": "market-level, identical for every user",
        "formula": {"C": "HHI of US import shares / 100", "P": "0.3 * raw-stage HHI/100 + 0.7 * processing-stage HHI/100",
                    "S": "min(100, 100 / (1 + N_eff) * D)", "N_eff": "sum over non-dominant producers of min(1, global share / 5)",
                    "base": "0.3 C + 0.4 P + 0.3 S", "G": "1.0 + sum of active event effects, capped at 1.5", "composite": "min(100, base * G)"},
        "event_effects": sc.EFFECT, "tiers": {"Low": "0-30", "Moderate": "above 30 to 60", "High": "above 60 to 80", "Critical": "above 80 to 100"},
        "validation": {"status": "Not validated as a predictor. Backtests found the index does not beat world-production concentration alone.",
                       "details": "See /validation and /api/v1/validation for the latest back-test, its labels and sources."},
        "limits": ["Figures are transcribed from USGS MCS 2024 tables and are unverified.",
                   "Processing-stage shares exist for cobalt and rare earths only (top supplier). Other materials use production shares (grade C, Indicative).",
                   "No alternate source has been verified by a person, so none earns credit. The score with every listed producer credited is shown as a sensitivity.",
                   "Substitution difficulty D is an unreviewed estimate (1.0) for every material.",
                   "The event layer runs in shadow mode and does not change any score."],
    }


# ---------- materials ----------
def _row(db, mid):
    m = taxonomy.MATERIALS[mid]
    sn = S.latest(db, mid)
    if not sn:
        return None
    return {"id": mid, "name": m["name"], "group": m["group"], "score": sc.round_score(sn.composite), "tier": sn.tier,
            "data_grade": sn.grade, "indicative": sn.grade in ("C", "none"), "range_low": sn.uncertainty["range_low"],
            "range_high": sn.uncertainty["range_high"], "dominant_country": m["dominant_country"],
            "dominant_share": round(m["production"]["shares"][0]["share"], 1), "snapshot_id": sn.id,
            "updated": sn.published_at.isoformat() + "Z", "data_as_of": sn.data_as_of}


@router.get("/materials")
def materials(q: str | None = None, db: Session = Depends(get_db)):
    rows = [r for r in (_row(db, mid) for mid in taxonomy.MATERIALS) if r]
    if q:
        ql = q.strip().lower()[:60]
        rows = [r for r in rows if ql in r["name"].lower() or any(ql in s for s in taxonomy.MATERIALS[r["id"]]["synonyms"])]
    rows.sort(key=lambda r: -r["score"])
    return {"count": len(rows), "materials": rows}


@router.get("/materials.csv")
def materials_csv(db: Session = Depends(get_db)):
    rows = [r for r in (_row(db, mid) for mid in taxonomy.MATERIALS) if r]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(sorted(rows, key=lambda r: -r["score"]))
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="material-exposure-scores.csv"'})


@router.get("/materials/{material_id}")
def material(material_id: str, db: Session = Depends(get_db)):
    v = assess.material_view(db, material_id)
    if not v:
        raise ApiError(404, "not_found", "Unknown material.")
    m = v["material"]
    return {"id": material_id, "name": m["name"], "group": m["group"], "snapshot": v["snapshot"],
            "inputs": {"import_shares": m["import"], "production_shares": m["production"], "processing": m["processing"],
                       "alternative_sources": m["alternative_sources"], "substitution_difficulty": m["substitution_difficulty"],
                       "baseline": {"top_producer": m["production"]["shares"][0]["country"], "top_producer_share_percent": m["production"]["shares"][0]["share"], "production_hhi": m["production"]["hhi"], "top_us_import_source": m["dominant_import_country"], "top_us_import_share_percent": m["import"]["shares"][0]["share"]},
                       "d_status": m["d_status"], "net_import_reliance_percent": m["nir"]},
            "divergence_note": v["divergence_note"], "indicative": v["indicative"], "reviewed_by_person": v["reviewed"],
            "under_review": v["under_review"]}


@router.get("/materials/{material_id}/history")
def history(material_id: str, db: Session = Depends(get_db)):
    if material_id not in taxonomy.MATERIALS:
        raise ApiError(404, "not_found", "Unknown material.")
    rows = db.execute(select(M.ScoreSnapshot).where(M.ScoreSnapshot.material_id == material_id).order_by(M.ScoreSnapshot.id)).scalars().all()
    return {"material_id": material_id, "snapshots": [{"snapshot_id": r.id, "score": sc.round_score(r.composite), "tier": r.tier,
                                                      "published_at": r.published_at.isoformat() + "Z",
                                                      "superseded_at": r.superseded_at.isoformat() + "Z" if r.superseded_at else None,
                                                      "payload_hash": r.payload_hash} for r in rows]}


@router.get("/materials/{material_id}/sources")
def sources(material_id: str, db: Session = Depends(get_db)):
    sn = S.latest(db, material_id) if material_id in taxonomy.MATERIALS else None
    if not sn:
        raise ApiError(404, "not_found", "Unknown material.")
    return {"material_id": material_id, "snapshot_id": sn.id, "citations": sn.citations,
            "guidance_note": "Recommendation guidance is cited separately per rule and currently rests on internal heuristics."}


@router.get("/materials/{material_id}/report.pdf")
def report(material_id: str, sourcing_region: str | None = None, volume_tier: str | None = None, db: Session = Depends(get_db)):
    if sourcing_region and sourcing_region not in recommend.REGION_KEYS or volume_tier and volume_tier not in recommend.VOLUME_KEYS:
        raise ApiError(422, "bad_param", "Unknown region or volume.")
    v = assess.material_view(db, material_id, sourcing_region, volume_tier)
    if not v:
        raise ApiError(404, "not_found", "Unknown material.")
    data = pdf.material_report(v["material"], v["snapshot"], v["recommendations"])
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="exposure-{material_id}.pdf"'})


# ---------- assess / scenarios ----------
@router.post("/assess")
def assess_ep(body: AssessIn, db: Session = Depends(get_db), x_session_token: str | None = Header(default=None)):
    sh = sessions.get(db, x_session_token)
    if body.material_id:
        if body.material_id not in taxonomy.MATERIALS:
            raise ApiError(404, "not_found", "Unknown material.")
        mid, method, cls = body.material_id, "dropdown", None
    elif body.material_description and body.material_description.strip():
        cls = assess.classify_text(db, body.material_description)
        method = cls["method"]
        if not cls["resolved"]:
            assess.track(db, "classifier_unresolved" if not cls["candidates"] else "classifier_low_confidence", method=method, session_hash=sh)
            return {"status": "needs_choice" if cls["candidates"] else "no_match", "confidence": cls["confidence"],
                    "candidates": [{"id": c, "name": taxonomy.MATERIALS[c]["name"]} for c in cls["candidates"]],
                    "message": "Pick the closest material from the tracked list." if cls["candidates"] else "No tracked material matched. Use the list."}
        mid = cls["resolved"]
    else:
        raise ApiError(422, "missing_input", "Provide material_description or material_id.")
    v = assess.material_view(db, mid, body.sourcing_region, body.volume_tier, record=True, method=method, session_hash=sh)
    if not v:
        raise ApiError(404, "not_found", "No published score for this material yet.")
    return {"status": "ok", "method": method, "confidence": cls["confidence"] if cls else None, "material_id": mid,
            "name": v["material"]["name"], "snapshot": v["snapshot"], "recommendations": v["recommendations"],
            "divergence_note": v["divergence_note"], "indicative": v["indicative"], "under_review": v["under_review"],
            "privacy": "Your description, region and volume were not stored.",
            "validation_status": "Not validated as a predictor. Backtests found the index does not beat world-production concentration alone."}


@router.post("/scenarios")
def scenarios(body: ScenarioIn, db: Session = Depends(get_db)):
    if body.family not in simulator.FAMILIES:
        raise ApiError(422, "bad_family", "Unknown scenario family.")
    try:
        r = assess.scenario_view(db, body.material_id, body.family, body.option, body.sourcing_region, body.volume_tier)
    except ValueError:
        raise ApiError(422, "bad_option", "Unknown option for this scenario.")
    if not r:
        raise ApiError(404, "not_found", "Unknown material.")
    return r


# ---------- snapshots ----------
@router.get("/snapshots/{snapshot_id}")
def snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    sn = db.get(M.ScoreSnapshot, snapshot_id)
    if not sn:
        raise ApiError(404, "not_found", "Unknown snapshot.")
    d = S.snapshot_dict(sn)
    d["payload"] = sn.payload
    return d


@router.get("/snapshots/{snapshot_id}/verify")
def verify(snapshot_id: int, db: Session = Depends(get_db)):
    sn = db.get(M.ScoreSnapshot, snapshot_id)
    if not sn:
        raise ApiError(404, "not_found", "Unknown snapshot.")
    res = S.recompute(sn.payload)
    hash_ok = S._h(sn.payload) == sn.payload_hash
    tier_ok = res["tier"] == sn.tier
    expl_ok = S.regenerate_explanations(sn.payload) == sorted(c["explanation"] for c in sn.citations if c.get("explanation"))
    ok = abs(res["composite"] - sn.composite) < 1e-9 and hash_ok and tier_ok and expl_ok
    return {"snapshot_id": snapshot_id, "reproduced": ok, "tier_matches": tier_ok, "explanation_matches": expl_ok, "stored_composite": sn.composite, "recomputed_composite": res["composite"],
            "payload_hash_matches": hash_ok, "formula_version": sn.formula_version, "digest": sn.digest, "prev_digest": sn.prev_digest}


@router.get("/log/verify")
def verify_log(db: Session = Depends(get_db)):
    """Walks the append-only snapshot log and regenerates every stored score."""
    return S.verify_chain(db)


# ---------- sectors ----------
def _sector_rows(db):
    out = []
    for s in taxonomy.SECTORS["sectors"]:
        r = db.execute(select(M.SectorScore).where(M.SectorScore.sector_id == s["id"], M.SectorScore.superseded_at.is_(None))).scalars().first()
        out.append({"id": s["id"], "name": s["name"], "naics": s["naics"], "materials": s["materials"],
                    "status": r.status if r else "not_scored", "score": sc.round_score(r.score) if r and r.score is not None else None,
                    "tier": r.tier if r else None, "top_material_id": r.top_material_id if r else None,
                    "reason": r.reason if r else None, "includes_indicative": bool(r and r.includes_indicative),
                    "indicative_view": S.sector_indicative(db, s) if not (r and r.status == "scored") else None,
                    "list_status": taxonomy.SECTORS["status"]})
    return out


@router.get("/sectors")
def sectors(db: Session = Depends(get_db)):
    return {"list_version": taxonomy.SECTORS["list_version"], "list_status": taxonomy.SECTORS["status"], "sectors": _sector_rows(db)}


@router.get("/sectors.csv")
def sectors_csv(db: Session = Depends(get_db)):
    rows = _sector_rows(db)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["sector_id", "sector", "status", "score", "tier", "highest_risk_material", "includes_indicative_inputs", "indicative_preview_score", "indicative_preview_tier", "list_status"])
    for r in rows:
        w.writerow([r["id"], r["name"], r["status"], r["score"], r["tier"], r["top_material_id"], r["includes_indicative"],
                    (r["indicative_view"] or {}).get("score"), (r["indicative_view"] or {}).get("tier"), r["list_status"]])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="sector-exposure.csv"'})


@router.get("/sectors/{sector_id}")
def sector(sector_id: str, db: Session = Depends(get_db)):
    for r in _sector_rows(db):
        if r["id"] == sector_id:
            r["member_scores"] = [x for x in (_row(db, mid) for mid in r["materials"]) if x]
            return r
    raise ApiError(404, "not_found", "Unknown sector.")


# ---------- sessions and watchlist ----------
@router.post("/sessions", status_code=201)
def new_session(db: Session = Depends(get_db)):
    return {"session_token": sessions.create(db), "note": "Keep this token. It is the only way to reach your watchlist. It is stored hashed."}


@router.delete("/session", status_code=204)
def delete_session(db: Session = Depends(get_db), x_session_token: str | None = Depends(tok)):
    h = session_hash(db, x_session_token)
    sessions.delete_all(db, h)
    return Response(status_code=204)


def _wl_rows(db, h):
    out = []
    for w in db.execute(select(M.Watchlist).where(M.Watchlist.session_hash == h).order_by(M.Watchlist.id)).scalars():
        row = _row(db, w.material_id)
        if not row:
            continue
        unseen = db.execute(select(func.count()).select_from(M.WatchlistEvent).where(M.WatchlistEvent.watchlist_id == w.id,
                                                                                    M.WatchlistEvent.seen_at.is_(None))).scalar() or 0
        out.append(dict(row, watchlist_id=w.id, alert_threshold=w.alert_threshold, unseen_changes=unseen))
    return out


@router.get("/watchlist")
def watchlist(db: Session = Depends(get_db), x_session_token: str | None = Depends(tok)):
    h = session_hash(db, x_session_token)
    return {"items": _wl_rows(db, h), "delivery": "In-app only. Changes appear when you return."}


@router.post("/watchlist", status_code=201)
def watch_add(body: WatchIn, db: Session = Depends(get_db), x_session_token: str | None = Depends(tok)):
    h = session_hash(db, x_session_token)
    if body.material_id not in taxonomy.MATERIALS:
        raise ApiError(404, "not_found", "Unknown material.")
    w = db.execute(select(M.Watchlist).where(M.Watchlist.session_hash == h, M.Watchlist.material_id == body.material_id)).scalars().first()
    if not w:
        n = db.execute(select(func.count()).select_from(M.Watchlist).where(M.Watchlist.session_hash == h)).scalar() or 0
        if n >= settings.max_watchlist:
            raise ApiError(409, "limit", f"Watchlist limit is {settings.max_watchlist}.")
        sn = S.latest(db, body.material_id)
        w = M.Watchlist(session_hash=h, material_id=body.material_id, last_seen_snapshot_id=sn.id if sn else None)
        db.add(w)
    w.alert_threshold = body.alert_threshold
    db.commit()
    return {"items": _wl_rows(db, h)}


@router.delete("/watchlist/{material_id}")
def watch_remove(material_id: str, db: Session = Depends(get_db), x_session_token: str | None = Depends(tok)):
    h = session_hash(db, x_session_token)
    w = db.execute(select(M.Watchlist).where(M.Watchlist.session_hash == h, M.Watchlist.material_id == material_id)).scalars().first()
    if w:
        db.query(M.WatchlistEvent).filter(M.WatchlistEvent.watchlist_id == w.id).delete()
        db.delete(w)
        db.commit()
    return {"items": _wl_rows(db, h)}


@router.get("/watchlist/changes")
def watch_changes(db: Session = Depends(get_db), x_session_token: str | None = Depends(tok)):
    h = session_hash(db, x_session_token)
    rows = db.execute(select(M.WatchlistEvent).join(M.Watchlist, M.Watchlist.id == M.WatchlistEvent.watchlist_id)
                      .where(M.Watchlist.session_hash == h).order_by(M.WatchlistEvent.id.desc()).limit(100)).scalars().all()
    return {"changes": [{"id": r.id, "material_id": r.material_id, "kind": r.kind, "summary": r.summary,
                         "created_at": r.created_at.isoformat() + "Z", "seen": r.seen_at is not None} for r in rows]}


@router.post("/watchlist/changes/seen")
def watch_seen(db: Session = Depends(get_db), x_session_token: str | None = Depends(tok)):
    h = session_hash(db, x_session_token)
    ids = [w.id for w in db.execute(select(M.Watchlist).where(M.Watchlist.session_hash == h)).scalars()]
    if ids:
        db.query(M.WatchlistEvent).filter(M.WatchlistEvent.watchlist_id.in_(ids), M.WatchlistEvent.seen_at.is_(None)).update(
            {"seen_at": M.now()}, synchronize_session=False)
        db.commit()
    return {"ok": True}


# ---------- corrections and events ----------
@router.post("/corrections", status_code=201)
def correction(body: CorrectionIn, db: Session = Depends(get_db)):
    if body.material_id not in taxonomy.MATERIALS:
        raise ApiError(404, "not_found", "Unknown material.")
    c = M.Correction(material_id=body.material_id, item=body.item.strip(), proposed_value=body.proposed_value.strip(),
                     source_link=body.source_link.strip(), note=body.note.strip())
    db.add(c)
    db.commit()
    return {"id": c.id, "status": "received", "policy": "Acknowledged within 5 business days. Decision within 15 business days. The decision is public."}


@router.get("/corrections")
def corrections(db: Session = Depends(get_db)):
    rows = db.execute(select(M.Correction).order_by(M.Correction.id.desc()).limit(200)).scalars().all()
    return {"corrections": [{"id": r.id, "material_id": r.material_id, "item": r.item, "proposed_value": r.proposed_value,
                             "source_link": r.source_link, "status": r.status, "decision_reason": r.decision_reason,
                             "received": r.created_at.date().isoformat(), "decided": r.decided_at.date().isoformat() if r.decided_at else None}
                            for r in rows]}


@router.get("/events")
def events(db: Session = Depends(get_db), limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = db.execute(select(M.EventRecord).order_by(M.EventRecord.id.desc()).limit(limit)).scalars().all()
    return {"mode": "shadow" if not settings.publish_events else "published",
            "events": [{"id": r.id, "created_at": r.created_at.isoformat() + "Z", "material_id": r.material_id, "country": r.country,
                        "instrument": r.instrument, "stage": r.stage, "status": r.status, "reasons": r.reasons, "quote": r.quote,
                        "source_url": r.source_url, "source_tier": r.source_tier, "content_hash": r.content_hash, "extractor": r.extractor,
                        "prompt_version": r.prompt_version, "reviewer": r.reviewer, "shadow": r.shadow,
                        "explanation": explain.explain_record(r)} for r in rows]}
