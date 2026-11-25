"""Score snapshots: compute, hash, publish, supersede, and raise in-app watchlist events (spec 3.3, 4.8, 4.10)."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .. import models as M
from ..config import settings
from ..engine import scoring as sc, uncertainty, taxonomy, explain
from . import chain

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


def active_events(db: Session, material_id: str) -> list[dict]:
    """The events that count toward G right now. Empty in shadow mode. Each carries a digest of its source text."""
    if not settings.publish_events:
        return []
    rows = db.execute(select(M.EventRecord).where(M.EventRecord.material_id == material_id,
                                                  M.EventRecord.status == "active").order_by(M.EventRecord.id)).scalars()
    return [{"country": r.country, "material": r.material_id, "instrument": r.instrument, "stage": r.stage,
             "effect": sc.EFFECT.get(r.stage, 0.0), "effective_date": r.effective_date, "host": r.source_host,
             "source_digest": r.content_hash, "source_url": r.source_url}
            for r in rows if r.stage]


def active_stages(db: Session, material_id: str) -> list[str]:
    return [e["stage"] for e in active_events(db, material_id)]


def shadow_stages(db: Session, material_id: str) -> list[str]:
    rows = db.execute(select(M.EventRecord.stage).where(M.EventRecord.material_id == material_id,
                                                         M.EventRecord.status == "shadow_active")).all()
    return [r[0] for r in rows if r[0]]


def build_payload(m: dict, events: list[dict]) -> dict:
    events = sorted(events, key=lambda e: (e["country"], e["instrument"], e["stage"]))
    return {
        "formula_version": sc.FORMULA_VERSION, "severity_table_version": sc.SEVERITY_TABLE_VERSION,
        "source_tier_table_version": sc.SOURCE_TIER_TABLE_VERSION, "hold_set_table_version": sc.HOLD_SET_TABLE_VERSION,
        "explanation_template_version": explain.TEMPLATE_VERSION, "weights": list(sc.WEIGHTS),
        "taxonomy_version": taxonomy.TAXONOMY_VERSION, "source_vintage": taxonomy.SOURCE_VINTAGE,
        "material_id": m["id"], "inputs": sc.inputs_from_material(m),
        "events": events, "event_stages": sorted(e["stage"] for e in events),
    }


def regenerate_explanations(payload: dict) -> list[str]:
    """The explanation sentences a payload implies, rebuilt from its events with the stored template."""
    return sorted(explain.explain(e, counted=True) for e in payload.get("events", []))


def recompute(payload: dict) -> dict:
    """Regenerate a score from a stored payload using the formula version the payload names."""
    if payload["formula_version"] not in sc.FORMULAS:
        raise ValueError(f"unknown formula version {payload['formula_version']}")
    stages = [e["stage"] for e in payload.get("events", [])] if "events" in payload else payload["event_stages"]
    return sc.FORMULAS[payload["formula_version"]](payload["inputs"], stages, tuple(payload["weights"]))


def citations_for(m: dict, db: Session | None = None) -> list[dict]:
    cites = [dict(e, type="evidence") for e in m["evidence"]]
    if db is not None and settings.publish_events:
        for r in db.execute(select(M.EventRecord).where(M.EventRecord.material_id == m["id"],
                                                         M.EventRecord.status == "active")).scalars():
            cites.append({"type": "evidence", "kind": "event", "label": f"{r.country}: {r.stage} ({r.instrument})",
                          "url": r.source_url, "tables": f"Source hash {r.content_hash}",
                          "effect": sc.EFFECT.get(r.stage, 0.0), "explanation": explain.explain_record(r, counted=True)})
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


def reviewed_material(db: Session, m: dict) -> dict:
    """The taxonomy record with people's alternate-source decisions applied (newest decision per country wins).
    A country with no decision keeps the status in the data file, which earns no credit unless it says 'qualified'."""
    rows = db.execute(select(M.AlternateSourceReview).where(M.AlternateSourceReview.material_id == m["id"])
                      .order_by(M.AlternateSourceReview.id)).scalars().all()
    if not rows:
        return m
    latest = {r.country: r for r in rows}
    out = dict(m)
    out["alternative_sources"] = []
    for a in m["alternative_sources"]:
        a = dict(a)
        r = latest.get(a["country"])
        if r:
            a["qualification_status"] = r.status
            a["included_in_n_alt"] = r.status == "qualified"
        out["alternative_sources"].append(a)
    return out


def verification_status(db: Session) -> dict:
    """How many materials have each data group checked against the published table by a person."""
    rows = db.execute(select(M.DataVerification.material_id, M.DataVerification.data_group, M.DataVerification.outcome)).all()
    done = {}
    for mid, grp, _ in rows:
        done.setdefault(mid, set()).add(grp)
    n = len(taxonomy.MATERIALS)
    full = sum(1 for mid in taxonomy.MATERIALS if {"import", "production"} <= done.get(mid, set()))
    reviews = db.execute(select(M.AlternateSourceReview.material_id, M.AlternateSourceReview.country, M.AlternateSourceReview.status)
                         .order_by(M.AlternateSourceReview.id)).all()
    latest = {(a, b): c for a, b, c in reviews}
    qualified = sorted({a for (a, b), c in latest.items() if c == "qualified"})
    return {"materials": n, "import_and_production_checked": full, "materials_with_qualified_alternate": len(qualified),
            "by_group": {g: sum(1 for v in done.values() if g in v) for g in ("import", "production", "processing")}}


def publish_all(db: Session, today: dt.date | None = None) -> dict:
    """Idempotent: a material whose payload hash is unchanged gets no new snapshot."""
    today = today or dt.date.today()
    ensure_materials(db)
    created, unchanged = [], []
    tail = db.execute(select(M.ScoreSnapshot.digest).where(M.ScoreSnapshot.digest.is_not(None))
                      .order_by(M.ScoreSnapshot.id.desc()).limit(1)).scalar() or chain.GENESIS
    changes = []
    for mid, m in taxonomy.MATERIALS.items():
        m = reviewed_material(db, m)
        events = active_events(db, mid)
        stages = [e["stage"] for e in events]
        payload = build_payload(m, events)
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
            model_version=MODEL_VERSION, prompt_version=PROMPT_VERSION, events_hash=_h(payload["events"]),
            payload=payload, payload_hash=ph,
            concentration=res["C"], processing_risk=res["P"], substitution_difficulty=res["S"],
            geopolitical_multiplier=res["G"], composite=res["composite"], tier=res["tier"], grade=grades["overall"],
            uncertainty=dict(unc, grades=grades, N_eff=res["N_eff"]), citations=citations_for(m, db),
            published_at=M.now(),
        )
        snap.prev_digest = tail
        snap.digest = chain.entry_digest(chain.entry_body(snap), tail)
        tail = snap.digest
        db.add(snap)
        db.flush()
        if cur:
            cur.superseded_at = M.now()
            _raise_watch_events(db, cur, snap)
            ch = material_change(cur, snap)
            if ch:
                changes.append(ch)
        created.append(mid)
    db.commit()
    sector_scores(db)
    return {"created": created, "unchanged": unchanged, "changes": changes}


def material_change(old: M.ScoreSnapshot, new: M.ScoreSnapshot) -> dict | None:
    """A change worth telling subscribers about: a new tier or a move of SCORE_MOVE_ALERT points or more.
    Indicative (grade C) data raises no alerts unless the deployment turns that on, as for watchlists."""
    if new.grade == "C" and not settings.indicative_alerts:
        return None
    moved = abs(sc.round_score(new.composite) - sc.round_score(old.composite))
    if new.tier == old.tier and moved < SCORE_MOVE_ALERT:
        return None
    return {"material_id": new.material_id, "name": taxonomy.MATERIALS[new.material_id]["name"], "from_score": sc.round_score(old.composite),
            "to_score": sc.round_score(new.composite), "from_tier": old.tier, "to_tier": new.tier, "snapshot_id": new.id,
            "tier_changed": new.tier != old.tier}


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
        snaps, missing, grade_c, indicative = [], [], [], False
        for mid in s["materials"]:
            sn = latest(db, mid)
            if sn is None or sn.grade == "none":
                missing.append(mid)
                continue
            if sn.grade == "C":
                if not settings.indicative_in_sectors:
                    grade_c.append(mid)
                    continue
                indicative = True
            snaps.append(sn)
        missing_all = missing + grade_c
        prev = db.execute(select(M.SectorScore).where(M.SectorScore.sector_id == s["id"],
                                                       M.SectorScore.superseded_at.is_(None))).scalars().first()
        ids = sorted(x.id for x in snaps)
        if missing_all:
            parts = []
            if grade_c:
                parts.append("only Indicative (grade C) data, which the method leaves out of sector means: " +
                             ", ".join(taxonomy.MATERIALS[m]["name"] for m in grade_c))
            if missing:
                parts.append("no usable published score: " + ", ".join(taxonomy.MATERIALS[m]["name"] for m in missing))
            row = dict(status="not_scored", score=None, tier=None, top=None, reason="Not scored. " + "; ".join(parts) + ".")
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


def sector_indicative(db: Session, sector: dict) -> dict | None:
    """A labelled preview mean that includes grade C materials. It is never stored, never used for alerts, and never
    shown as the sector score. None when any member has no published score at all."""
    snaps = []
    for mid in sector["materials"]:
        sn = latest(db, mid)
        if sn is None or sn.grade == "none":
            return None
        snaps.append(sn)
    avg = sum(x.composite for x in snaps) / len(snaps)
    top = max(snaps, key=lambda x: x.composite)
    return {"score": sc.round_score(avg), "tier": sc.tier_of(avg), "top_material_id": top.material_id,
            "grade_c_members": [x.material_id for x in snaps if x.grade == "C"],
            "label": "Indicative preview. Includes materials with grade C data. Not a sector score."}


def top_explanation(sn: M.ScoreSnapshot) -> str | None:
    """Sentence for the active event that adds most to the multiplier (patent paragraph 0077)."""
    ev = [c for c in sn.citations if c.get("explanation")]
    return max(ev, key=lambda c: c.get("effect", 0.0))["explanation"] if ev else None


def snapshot_dict(sn: M.ScoreSnapshot) -> dict:
    return {
        "explanation": top_explanation(sn),
        "snapshot_id": sn.id, "material_id": sn.material_id, "composite": round(sn.composite, 2), "score": sc.round_score(sn.composite),
        "tier": sn.tier, "components": {
            "concentration": round(sn.concentration, 1), "processing_risk": round(sn.processing_risk, 1),
            "substitution_difficulty": round(sn.substitution_difficulty, 1), "geopolitical_multiplier": round(sn.geopolitical_multiplier, 3)},
        "data_grade": sn.grade, "uncertainty": sn.uncertainty, "formula_version": sn.formula_version,
        "taxonomy_version": sn.taxonomy_version, "data_as_of": sn.data_as_of, "model_version": sn.model_version,
        "prompt_version": sn.prompt_version, "payload_hash": sn.payload_hash, "events_hash": sn.events_hash,
        "digest": sn.digest, "prev_digest": sn.prev_digest,
        "published_at": sn.published_at.isoformat() + "Z", "superseded_at": sn.superseded_at.isoformat() + "Z" if sn.superseded_at else None,
        "citations": sn.citations,
    }


def verify_chain(db: Session) -> dict:
    """Walk the whole log. Intact means: every entry links to the one before, every digest matches its content,
    and every stored score regenerates from its stored payload."""
    rows = db.execute(select(M.ScoreSnapshot).order_by(M.ScoreSnapshot.id).execution_options(populate_existing=True)).scalars().all()
    prev, n, unchained, first_break = chain.GENESIS, 0, 0, None
    for sn in rows:
        if sn.digest is None:
            unchained += 1
            continue
        n += 1
        ok = sn.prev_digest == prev and sn.digest == chain.entry_digest(chain.entry_body(sn), prev) \
            and _h(sn.payload) == sn.payload_hash
        if ok:
            try:
                res = recompute(sn.payload)
                ok = abs(res["composite"] - sn.composite) < 1e-9 and res["tier"] == sn.tier \
                    and regenerate_explanations(sn.payload) == sorted(c["explanation"] for c in sn.citations if c.get("explanation"))
            except Exception:
                ok = False
        if not ok and first_break is None:
            first_break = sn.id
        prev = sn.digest
    return {"entries": n, "unchained_legacy_entries": unchained, "intact": first_break is None, "first_break_snapshot_id": first_break,
            "head_digest": prev if n else None}
