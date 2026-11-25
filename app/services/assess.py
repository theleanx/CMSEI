"""Assessment flow shared by the API and the web app. Region and volume are used here in memory only."""
from __future__ import annotations
import datetime as dt
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models as M
from ..config import settings
from ..engine import classifier, recommend, taxonomy, scoring as sc, simulator
from . import snapshots as S

_client = None


def claude_client():
    """Lazy Anthropic client. None when no key or when the mode forces the offline path."""
    global _client
    if settings.classifier_mode == "lexical" or not settings.anthropic_api_key:
        return None
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=1, timeout=10.0)
    return _client


def budget_ok(db: Session) -> bool:
    """Spend caps (remediation pack section 6): a daily and a monthly call cap, counted in the database."""
    d, m = dt.date.today(), dt.date.today().strftime("%Y-%m")
    day_row, mon_row = db.get(M.Counter, f"claude:{d}"), db.get(M.Counter, f"claude:{m}")
    return (day_row.value if day_row else 0) < settings.claude_daily_call_cap and \
           (mon_row.value if mon_row else 0) < settings.claude_monthly_call_cap


def count_call(db: Session) -> None:
    for k in (f"claude:{dt.date.today()}", f"claude:{dt.date.today().strftime('%Y-%m')}"):
        row = db.get(M.Counter, k)
        if row:
            row.value += 1
        else:
            db.add(M.Counter(key=k, value=1))
    db.commit()


def classify_text(db: Session, text: str) -> dict:
    client = claude_client()
    if client is not None and not budget_ok(db):
        client = None
    if client is not None:
        count_call(db)
    return classifier.classify(text, client, settings.claude_model if client else None)


def track(db: Session, kind: str, material_id: str | None = None, tier: str | None = None, method: str | None = None,
          session_hash: str | None = None) -> None:
    db.add(M.Analytics(day=dt.date.today().isoformat(), kind=kind, material_id=material_id, tier=tier, method=method,
                       session_hash=session_hash))
    db.commit()


def material_view(db: Session, material_id: str, region: str | None = None, volume: str | None = None,
                  record: bool = False, method: str | None = None, session_hash: str | None = None) -> dict | None:
    m = taxonomy.MATERIALS.get(material_id)
    snap = S.latest(db, material_id) if m else None
    if not m or not snap:
        return None
    sd = S.snapshot_dict(snap)
    recs = recommend.select(m, snap.tier, region, volume)
    if record:
        db.add(M.Assessment(material_id=material_id, snapshot_id=snap.id, recommendation_rule_ids=[r["rule_id"] for r in recs]))
        db.commit()
        track(db, "assessment", material_id, snap.tier, method, session_hash)
    shadow = S.shadow_stages(db, material_id)
    return {
        "material": m, "snapshot": sd, "recommendations": recs,
        "divergence_note": sc.divergence_note(m),
        "stale": False, "shadow_events": len(shadow),
        "under_review": db.execute(select(M.EventRecord.id).where(M.EventRecord.material_id == material_id,
                                                                  M.EventRecord.status == "held")).first() is not None,
        "indicative": sd["data_grade"] in ("C", "none"),
        "reviewed": db.get(M.Material, material_id).signed_off_by is not None,
    }


def scenario_view(db: Session, material_id: str, family: str, option: str | None, region: str | None, volume: str | None) -> dict | None:
    m = taxonomy.MATERIALS.get(material_id)
    snap = S.latest(db, material_id) if m else None
    if not m or not snap:
        return None
    inp = snap.payload["inputs"]
    stages = snap.payload["event_stages"]
    res = simulator.simulate(inp, stages, family, option)
    sim_tier = res["simulated"]["tier"]
    recs = recommend.select(m, sim_tier, region, volume, scenario=True)
    return {"result": res, "recommendations": recs, "official_snapshot_id": snap.id}
