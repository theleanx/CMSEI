"""Score snapshots: compute, hash, publish, supersede, and raise in-app watchlist events (spec 3.3, 4.8, 4.10)."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .. import models as M
from ..config import settings
from ..engine import scoring as sc, uncertainty, taxonomy

MODEL_VERSION = "none-scores-are-rule-based"
PROMPT_VERSION = "n/a"
GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "none": 3}
SCORE_MOVE_ALERT = 5


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def effective_grade(grade: str, data_year: int, today: dt.date) -> str:
    """Spec 4.8: official data over 24 months old cannot be A; past 48 months the grade drops one more step."""
    age_months = (today.year - data_year) * 12 + (today.month - 12)
    g = grade
    if age_months > 24 and g == "A":
        g = "B"
    if age_months > 48:
        g = {"A": "B", "B": "C", "C": "none", "none": "none"}[g]
    return g


def grades_for(m: dict, today: dt.date) -> dict:
    comp = {
        "concentration": effective_grade(m["import"]["grade"], m["import"]["data_year"], today),
        "production": effective_grade(m["production"]["grade"], m["production"]["data_year"], today),
        "processing": effective_grade(m["processing"]["grade"], m["processing"]["data_year"], today),
    }
    worst = max(comp.values(), key=lambda g: GRADE_ORDER[g])
    comp["overall"] = worst
    return comp


def active_stages(db: Session, material_id: str) -> list[str]:
    want = "active" if settings.publish_events else None
    if want is None:
        return []
    rows = db.execute(select(M.EventRecord.stage).where(M.EventRecord.material_id == material_id,
                                                         M.EventRecord.status == "active")).all()
    return [r[0] for r in rows if r[0]]


def shadow_stages(db: Session, material_id: str) -> list[str]:
    rows = db.execute(select(M.EventRecord.stage).where(M.EventRecord.material_id == material_id,
                                                         M.EventRecord.status == "shadow_active")).all()
    return [r[0] for r in rows if r[0]]


def build_payload(m: dict, stages: list[str]) -> dict:
    return {
        "formula_version": sc.FORMULA_VERSION, "weights": list(sc.WEIGHTS),
        "taxonomy_version": taxonomy.TAXONOMY_VERSION, "source_vintage": taxonomy.SOURCE_VINTAGE,
        "material_id": m["id"], "inputs": sc.inputs_from_material(m), "event_stages": sorted(stages),
    }


def recompute(payload: dict) -> dict:
    return sc.score_inputs(payload["inputs"], payload["event_stages"], tuple(payload["weights"]))


def citations_for(m: dict, db: Session | None = None) -> list[dict]:
    cites = [dict(e, type="evidence") for e in m["evidence"]]
    if db is not None and settings.publish_events:
        for r in db.execute(select(M.EventRecord).where(M.EventRecord.material_id == m["id"],
                                                         M.EventRecord.status == "active")).scalars():
            cites.append({"type": "evidence", "kind": "event", "label": f"{r.country}: {r.stage} ({r.instrument})",
                          "url": r.source_url, "tables": f"Source hash {r.content_hash}"})
    return cites


def ensure_materials(db: Session) -> None:
    for mid, m in taxonomy.MATERIALS.items():
        row = db.get(M.Material, mid)
        if row is None:
            db.add(M.Material(id=mid, name=m["name"], grp=m["group"], record=m, taxonomy_version=taxonomy.TAXONOMY_VERSION))
        else:
            row.name, row.grp, row.record, row.taxonomy_version = m["name"], m["group"], m, taxonomy.TAXONOMY_VERSION
    db.commit()


def latest(db: Session, material_id: str) -> M.ScoreSnapshot | None:
    return db.execute(select(M.ScoreSnapshot).where(M.ScoreSnapshot.material_id == material_id,
                                                     M.ScoreSnapshot.superseded_at.is_(None))
                      .order_by(M.ScoreSnapshot.id.desc())).scalars().first()


def publish_all(db: Session, today: dt.date | None = None) -> dict:
    """Idempotent: a material whose payload hash is unchanged gets no new snapshot."""
    today = today or dt.date.today()
    ensure_materials(db)
    created, unchanged = [], []
    for mid, m in taxonomy.MATERIALS.items():
        stages = active_stages(db, mid)
        payload = build_payload(m, stages)
        ph = _h(payload)
        cur = latest(db, mid)
        if cur and cur.payload_hash == ph:
            unchanged.append(mid)
            continue
        res = recompute(payload)
        unc = uncertainty.run(mid, payload["inputs"], tuple(stages))
        grades = grades_for(m, today)
        snap = M.ScoreSnapshot(
            material_id=mid, formula_version=sc.FORMULA_VERSION, taxonomy_version=taxonomy.TAXONOMY_VERSION,
            data_as_of=taxonomy.SOURCE_VINTAGE,
            source_snapshot={"source": taxonomy.SOURCE_VINTAGE, "material_record_hash": _h(m), "transcription": m["transcription"]},
            model_version=MODEL_VERSION, prompt_version=PROMPT_VERSION, events_hash=_h(sorted(stages)),
            payload=payload, payload_hash=ph,
            concentration=res["C"], processing_risk=res["P"], substitution_difficulty=res["S"],
            geopolitical_multiplier=res["G"], composite=res["composite"], tier=res["tier"], grade=grades["overall"],
            uncertainty=dict(unc, grades=grades, N_eff=res["N_eff"]), citations=citations_for(m, db),
        )
        db.add(snap)
        db.flush()
        if cur:
            cur.superseded_at = M.now()
            _raise_watch_events(db, cur, snap)
        created.append(mid)
    db.commit()
    sector_scores(db)
    return {"created": created, "unchanged": unchanged}


def _raise_watch_events(db: Session, old: M.ScoreSnapshot, new: M.ScoreSnapshot) -> None:
    if new.grade == "C" and not settings.indicative_alerts:
        return
    moved = abs(sc.round_score(new.composite) - sc.round_score(old.composite))
    tier_change = new.tier != old.tier
    if not tier_change and moved < SCORE_MOVE_ALERT:
        return
    for w in db.execute(select(M.Watchlist).where(M.Watchlist.material_id == new.material_id)).scalars():
        kind = "tier_change" if tier_change else "score_move"
        if w.alert_threshold is not None and not tier_change:
            crossed = (old.composite < w.alert_threshold <= new.composite) or (new.composite < w.alert_threshold <= old.composite)
            if not crossed:
                continue
            kind = "threshold"
        db.add(M.WatchlistEvent(
            watchlist_id=w.id, material_id=new.material_id, from_snapshot_id=old.id, to_snapshot_id=new.id, kind=kind,
            summary=f"{taxonomy.MATERIALS[new.material_id]['name']}: {sc.round_score(old.composite)} ({old.tier}) to "
                    f"{sc.round_score(new.composite)} ({new.tier})"))


def sector_scores(db: Session) -> list[dict]:
    """Spec 4.7. Average of published composites, highest-risk material shown beside it. Scored only when every
    listed material has a published score. Grade C inputs are excluded unless the preview setting includes them."""
    out = []
    for s in taxonomy.SECTORS["sectors"]:
        snaps, missing, indicative = [], [], False
        for mid in s["materials"]:
            sn = latest(db, mid)
            if sn is None:
                missing.append(mid)
                continue
            if sn.grade in ("C", "none"):
                if sn.grade == "none" or not settings.indicative_in_sectors:
                    missing.append(mid)
                    continue
                indicative = True
            snaps.append(sn)
        prev = db.execute(select(M.SectorScore).where(M.SectorScore.sector_id == s["id"],
                                                       M.SectorScore.superseded_at.is_(None))).scalars().first()
        ids = sorted(x.id for x in snaps)
        if missing:
            row = dict(status="not_scored", score=None, tier=None, top=None,
                       reason="No usable published score for: " + ", ".join(missing))
        else:
            avg = sum(x.composite for x in snaps) / len(snaps)
            top = max(snaps, key=lambda x: x.composite)
            row = dict(status="scored", score=avg, tier=sc.tier_of(avg), top=top.material_id, reason=None)
        same = prev and prev.snapshot_ids == ids and prev.status == row["status"] and prev.list_version == taxonomy.SECTORS["list_version"] \
            and prev.includes_indicative == indicative
        if not same:
            if prev:
                prev.superseded_at = M.now()
            db.add(M.SectorScore(sector_id=s["id"], sector_name=s["name"], snapshot_ids=ids, score=row["score"], tier=row["tier"],
                                 top_material_id=row["top"], status=row["status"], reason=row["reason"],
                                 list_version=taxonomy.SECTORS["list_version"], includes_indicative=indicative))
        out.append(row)
    db.commit()
    return out


def snapshot_dict(sn: M.ScoreSnapshot) -> dict:
    return {
        "snapshot_id": sn.id, "material_id": sn.material_id, "composite": round(sn.composite, 2), "score": sc.round_score(sn.composite),
        "tier": sn.tier, "components": {
            "concentration": round(sn.concentration, 1), "processing_risk": round(sn.processing_risk, 1),
            "substitution_difficulty": round(sn.substitution_difficulty, 1), "geopolitical_multiplier": round(sn.geopolitical_multiplier, 3)},
        "data_grade": sn.grade, "uncertainty": sn.uncertainty, "formula_version": sn.formula_version,
        "taxonomy_version": sn.taxonomy_version, "data_as_of": sn.data_as_of, "model_version": sn.model_version,
        "prompt_version": sn.prompt_version, "payload_hash": sn.payload_hash, "events_hash": sn.events_hash,
        "published_at": sn.published_at.isoformat() + "Z", "superseded_at": sn.superseded_at.isoformat() + "Z" if sn.superseded_at else None,
        "citations": sn.citations,
    }
