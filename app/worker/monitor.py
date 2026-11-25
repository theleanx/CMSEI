"""Event monitor (spec 4.9): AI reads, fixed rules verify, people approve.

Shadow mode (default): everything runs and is logged, events become `shadow_active`, and no published score changes.
Live mode (PUBLISH_EVENTS=true): events become `active` and feed G. Do not enable live mode before the go-live test
in spec 4.9 item 10 (300 hand-labeled documents, precision >= 0.95 and recall >= 0.80 for stages enacted and above,
prompt-injection set, 60 days in shadow mode).
"""
from __future__ import annotations
import datetime as dt
import hashlib
import logging
from collections import defaultdict
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models as M
from ..config import settings
from ..engine import scoring as sc, taxonomy
from ..services import snapshots as S, assess
from . import gate, extractors, fetch

log = logging.getLogger("mse.monitor")
DECAY_DAYS = gate.DECAY_DAYS
HOLD_EXPIRY_HOURS = gate.HOLD_EXPIRY_HOURS
RUN_POINT_CAP = gate.RUN_POINT_CAP
LIVE = ("active", "shadow_active")


def _live_status() -> str:
    return "active" if settings.publish_events else "shadow_active"


class job:
    """Context manager recording a JobRun."""
    def __init__(self, db: Session, name: str):
        self.db, self.name = db, name

    def __enter__(self):
        self.run = M.JobRun(job=self.name)
        self.db.add(self.run)
        self.db.commit()
        return self.run

    def __exit__(self, et, ev, tb):
        self.run.finished_at = M.now()
        self.run.status = "failed" if et else "ok"
        if et:
            self.run.detail = dict(self.run.detail or {}, error=type(ev).__name__)
        else:
            self.run.detail = dict(self.run.detail or {})
        self.db.commit()
        return False


# ---------------------------------------------------------------- intake
def process_document(db: Session, doc: dict, candidates: list, run_date: dt.date, extractor: str) -> dict:
    ch = hashlib.sha256(gate.norm(doc["text"]).encode()).hexdigest()
    if db.execute(select(M.EventRecord.id).where(M.EventRecord.content_hash == ch, M.EventRecord.source_url == doc.get("url")).limit(1)).first():
        return {"skipped": True, "n": 0, "rejected": 0}
    tier = gate.ALLOWLIST.get(doc.get("host"), (None, None))[0]
    n = rej = 0
    for c in candidates if isinstance(candidates, list) else []:
        reasons = gate.check_schema(c)
        if not reasons:
            reasons = gate.validate(c, doc, run_date)
        ok = isinstance(c, dict)
        def g(k, cap=128):
            v = c.get(k) if ok else None
            return v[:cap] if isinstance(v, str) else None
        rec = M.EventRecord(
            material_id=g("material") if g("material") in taxonomy.MATERIALS else None, country=g("country"), instrument=g("instrument"),
            stage=g("stage"), event_type=g("event_type"), effective_date=g("effective_date", 10), quote=g("quote", 400),
            source_url=(doc.get("url") or "")[:512], source_host=(doc.get("host") or "")[:128], source_tier=tier, content_hash=ch,
            extractor=extractor, prompt_version=extractors.PROMPT_VERSION if extractor.startswith("claude") else "keyword-baseline",
            reasons=reasons, status="rejected" if reasons else "pending_corroboration", shadow=not settings.publish_events)
        db.add(rec)
        n += 1
        rej += 1 if reasons else 0
    db.commit()
    return {"skipped": False, "n": n, "rejected": rej}


def _jaccard_shingles(a: str, b: str) -> float:
    return gate.jaccard(gate.shingles(gate.norm(a or ""), 4), gate.shingles(gate.norm(b or ""), 4))


def _clusters(recs):
    clusters = []
    for r in recs:
        for cl in clusters:
            if r.source_host == cl[0].source_host or _jaccard_shingles(r.quote, cl[0].quote) >= 0.5:
                cl.append(r)
                break
        else:
            clusters.append([r])
    return clusters


def qualify_pool(db: Session, today: dt.date) -> dict:
    """Sourcing rules (spec 4.9 item 2). Enacted and ban need the issuing government's own text. Statements and
    proposals need two independent sources. One outlet alone never counts; copies of one story count once."""
    out = {"qualified": 0, "pending": 0, "expired": 0}
    pend = db.execute(select(M.EventRecord).where(M.EventRecord.status.like("pending%"))).scalars().all()
    groups = defaultdict(list)
    for r in pend:
        if (today - r.created_at.date()).days > gate.FRESH_DAYS:
            r.status = "expired"
            out["expired"] += 1
            continue
        groups[(r.event_type, r.material_id, r.country, r.instrument, r.stage)].append(r)
    for (et, mat, cty, ins, st), rs in groups.items():
        tier1_issuer = any(gate.ALLOWLIST.get(r.source_host, (0, None)) == (1, cty) for r in rs)
        n_ind = len(_clusters(rs))
        if st in ("enacted", "ban"):
            ok, why = tier1_issuer, "pending_official_text"
        elif et == "withdrawal":
            ok, why = tier1_issuer or n_ind >= 2, "pending_corroboration"
        else:
            ok, why = n_ind >= 2, "pending_corroboration"
        for r in rs:
            r.status = "qualified" if ok else why
        out["qualified" if ok else "pending"] += 1
    db.commit()
    return out


# ---------------------------------------------------------------- state machine
def _live_stages(db: Session, material_id: str, extra: list | None = None, drop_key: tuple | None = None) -> list[str]:
    rows = db.execute(select(M.EventRecord).where(M.EventRecord.material_id == material_id, M.EventRecord.status.in_(LIVE))).scalars().all()
    stages = [r.stage for r in rows if not (drop_key and (r.country, r.instrument) == drop_key)]
    return stages + (extra or [])


def _published(db: Session, material_id: str):
    return S.latest(db, material_id)


def _apply(db: Session, rec: M.EventRecord, today: dt.date, who: str | None = None) -> None:
    key = (rec.material_id, rec.country, rec.instrument)
    olds = db.execute(select(M.EventRecord).where(M.EventRecord.material_id == rec.material_id, M.EventRecord.country == rec.country,
                                                   M.EventRecord.instrument == rec.instrument, M.EventRecord.status.in_(LIVE),
                                                   M.EventRecord.id != rec.id)).scalars().all()
    if rec.event_type == "withdrawal":
        for o in olds:
            o.status = "removed"
        rec.status = "applied"
    else:
        keep = None
        for o in olds:
            if gate.RANK.get(o.stage, 0) > gate.RANK.get(rec.stage, 0):
                keep = o                       # a lower stage never replaces a higher one
            elif gate.RANK.get(o.stage, 0) == gate.RANK.get(rec.stage, 0):
                o.last_verified = M.now()      # renewal
                keep = o
            else:
                o.status = "superseded"        # stages never stack
        if keep is not None:
            rec.status = "superseded"
        else:
            rec.status = _live_status()
            rec.last_verified = M.now()
    if who:
        rec.reviewer = who
    rec.hold_reason = None if rec.status != "held" else rec.hold_reason


def apply_qualified(db: Session, today: dt.date) -> dict:
    summary = {"auto": 0, "held": 0}
    recs = db.execute(select(M.EventRecord).where(M.EventRecord.status == "qualified").order_by(M.EventRecord.id)).scalars().all()
    by_key = defaultdict(list)
    for r in recs:
        by_key[(r.material_id, r.country, r.instrument, r.stage, r.event_type)].append(r)
    for key, rs in by_key.items():
        rep = rs[0]
        for dup in rs[1:]:
            dup.status = "superseded"
        mat = rep.material_id
        snap = _published(db, mat)
        if mat not in taxonomy.MATERIALS or snap is None:
            rep.status = "rejected"
            rep.reasons = (rep.reasons or []) + ["X_no_published_score"]
            continue
        firm = rep.stage in ("enacted", "ban")
        lifts = rep.event_type == "withdrawal" and db.execute(select(M.EventRecord.id).where(
            M.EventRecord.material_id == mat, M.EventRecord.country == rep.country, M.EventRecord.instrument == rep.instrument,
            M.EventRecord.status.in_(LIVE), M.EventRecord.stage.in_(("enacted", "ban")))).first() is not None
        reason = "enacted_or_above" if firm else ("lifts_firm_event" if lifts else None)
        if reason is None:
            inp = snap.payload["inputs"]
            drop = (rep.country, rep.instrument)
            if rep.event_type == "withdrawal":
                stages = _live_stages(db, mat, drop_key=drop)
            else:
                stages = _live_stages(db, mat, extra=[rep.stage], drop_key=drop)
            target = sc.score_inputs(inp, stages)["composite"]
            base_pub = snap.composite
            if sc.tier_of(target) != sc.tier_of(base_pub):
                reason = "tier_change"
            elif abs(target - base_pub) > RUN_POINT_CAP:
                reason = "point_cap"
        if reason:
            rep.status, rep.hold_reason, rep.held_at = "held", reason, M.now()
            summary["held"] += 1
        else:
            _apply(db, rep, today)
            summary["auto"] += 1
    db.commit()
    return summary


def decide_held(db: Session, eid: int, approve: bool, who: str) -> None:
    rec = db.get(M.EventRecord, eid)
    if not rec or rec.status != "held":
        return
    if approve:
        _apply(db, rec, dt.date.today(), who)
    else:
        rec.status, rec.reviewer = "rejected", who
        rec.reasons = (rec.reasons or []) + ["H_rejected_by_reviewer"]
    db.commit()
    if settings.publish_events:
        S.publish_all(db)


def decay_and_expire(db: Session, today: dt.date) -> dict:
    exp = holds = 0
    for r in db.execute(select(M.EventRecord).where(M.EventRecord.status.in_(LIVE))).scalars():
        lim = DECAY_DAYS.get(r.stage)
        if lim and r.last_verified and (today - r.last_verified.date()).days > lim:
            r.status = "expired"
            exp += 1
    for r in db.execute(select(M.EventRecord).where(M.EventRecord.status == "held")).scalars():
        if r.held_at and (M.now() - r.held_at).total_seconds() / 3600 > HOLD_EXPIRY_HOURS:
            r.status = "expired"                     # held items expire, they never auto-publish
            r.reasons = (r.reasons or []) + ["H_hold_expired_72h"]
            holds += 1
    db.commit()
    return {"decayed": exp, "holds_expired": holds}


def reverify(db: Session, today: dt.date | None = None, client=None) -> dict:
    """Enacted and ban events are re-checked against their source every 30 days. Two failed checks remove the event."""
    today = today or dt.date.today()
    checked = removed = 0
    close = False
    if client is None:
        import httpx
        client, close = httpx.Client(), True
    try:
        for r in db.execute(select(M.EventRecord).where(M.EventRecord.status.in_(LIVE), M.EventRecord.stage.in_(("enacted", "ban")))).scalars():
            if r.last_verified and (today - r.last_verified.date()).days < gate.REVERIFY_DAYS:
                continue
            checked += 1
            try:
                text = gate.norm(fetch.get_text(client, r.source_url))
                ok = gate.norm(r.quote or "") in text
            except Exception:
                ok = False
            if ok:
                r.last_verified, r.verify_failures = M.now(), 0
            else:
                r.verify_failures += 1
                if r.verify_failures >= 2:
                    r.status = "removed"
                    removed += 1
        db.commit()
    finally:
        if close:
            client.close()
    return {"checked": checked, "removed": removed}


# ---------------------------------------------------------------- job entry points
def run_monitor(db: Session, today: dt.date | None = None, docs: list | None = None, extractor=None) -> dict:
    today = today or dt.date.today()
    with job(db, "monitor") as jr:
        if docs is None:
            import httpx
            with httpx.Client() as c:
                docs = fetch.collect(c)
        name = "keyword-baseline"
        use_claude = extractor is None and settings.extractor_mode != "keyword" and bool(settings.anthropic_api_key)
        client = assess.claude_client() if use_claude else None
        if extractor is None:
            if client is not None:
                name = "claude:" + settings.claude_model
                extractor = lambda d: extractors.claude_extract(client, settings.claude_model, d)
            else:
                extractor = extractors.keyword_extract
        n_docs = n_cands = n_rej = 0
        for d in docs:
            if client is not None:
                if not assess.budget_ok(db):
                    log.warning("Claude call cap reached; stopping extraction")
                    break
                assess.count_call(db)
            try:
                cands = extractor(d)
            except Exception:
                cands = []
            r = process_document(db, d, cands, today, name)
            if not r["skipped"]:
                n_docs += 1
                n_cands += r["n"]
                n_rej += r["rejected"]
        q = qualify_pool(db, today)
        a = apply_qualified(db, today)
        dec = decay_and_expire(db, today)
        if settings.publish_events:
            S.publish_all(db)
        jr.detail = {"documents": n_docs, "candidates": n_cands, "rejected": n_rej, "extractor": name,
                     "mode": "live" if settings.publish_events else "shadow", **q, **a, **dec}
        return jr.detail
