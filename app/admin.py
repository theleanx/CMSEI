"""Reviewer console (HTTP Basic). Disabled unless ADMIN_PASSWORD is set. Humans approve held events, decide corrections,
and sign off each material's first data load (spec 4.8, 4.9 item 8)."""
from __future__ import annotations
import hmac
import secrets
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import models as M
from .config import settings
from .db import get_db
from .engine import taxonomy
from .services import snapshots as S

router = APIRouter(prefix="/admin")
basic = HTTPBasic(auto_error=False)


def reviewer(creds: HTTPBasicCredentials | None = Depends(basic)) -> str:
    if not settings.admin_password:
        raise HTTPException(404, "Not found")
    ok = creds is not None and hmac.compare_digest(creds.password.encode(), settings.admin_password.encode())
    if not ok:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": 'Basic realm="reviewer"'})
    return (creds.username or "reviewer")[:48]


@router.get("", response_class=HTMLResponse)
def home(request: Request, who: str = Depends(reviewer), db: Session = Depends(get_db)):
    from .web import render
    held = db.execute(select(M.EventRecord).where(M.EventRecord.status == "held").order_by(M.EventRecord.id)).scalars().all()
    pending = db.execute(select(M.EventRecord).where(M.EventRecord.status.like("pending%")).order_by(M.EventRecord.id.desc()).limit(30)).scalars().all()
    corr = db.execute(select(M.Correction).where(M.Correction.status == "received").order_by(M.Correction.id)).scalars().all()
    mats = db.execute(select(M.Material).order_by(M.Material.name)).scalars().all()
    quar = db.execute(select(M.QuarantinedDocument).order_by(M.QuarantinedDocument.id.desc()).limit(50)).scalars().all()
    vers = db.execute(select(M.DataVerification).order_by(M.DataVerification.id.desc()).limit(40)).scalars().all()
    revs = db.execute(select(M.AlternateSourceReview).order_by(M.AlternateSourceReview.id.desc()).limit(40)).scalars().all()
    alt = {k: [a["country"] for a in v["alternative_sources"]] for k, v in taxonomy.MATERIALS.items()}
    return render(request, "admin.html", {"who": who, "held": held, "pending": pending, "corr": corr, "mats": mats, "quar": quar,
                                          "vers": vers, "revs": revs, "alt": alt, "status": S.verification_status(db)})


@router.post("/event/{eid}")
def event_decide(eid: int, request: Request, decision: str = Form(...), csrf: str = Form(""), who: str = Depends(reviewer), db: Session = Depends(get_db)):
    from .web import check_csrf
    from .worker import monitor
    check_csrf(request, csrf)
    if decision not in ("approve", "reject"):
        raise HTTPException(422, "bad decision")
    monitor.decide_held(db, eid, decision == "approve", who)
    return RedirectResponse("/admin", status_code=303)


@router.post("/correction/{cid}")
def correction_decide(cid: int, request: Request, decision: str = Form(...), reason: str = Form("", max_length=500), csrf: str = Form(""),
                      who: str = Depends(reviewer), db: Session = Depends(get_db)):
    from .web import check_csrf
    check_csrf(request, csrf)
    c = db.get(M.Correction, cid)
    if not c or decision not in ("accepted", "declined"):
        raise HTTPException(422, "bad request")
    if decision == "declined" and not reason.strip():
        raise HTTPException(422, "A declined correction needs a stated reason.")
    c.status, c.decision_reason, c.decided_at = decision, reason.strip() or None, M.now()
    db.commit()
    return RedirectResponse("/admin", status_code=303)


DATA_GROUPS = ("import", "production", "processing")


@router.post("/verify/{mid}")
def verify(mid: str, request: Request, data_group: str = Form(...), outcome: str = Form(...), source_doc: str = Form(..., min_length=8, max_length=300),
           note: str = Form("", max_length=1000), csrf: str = Form(""), who: str = Depends(reviewer), db: Session = Depends(get_db)):
    """Record that a person compared one group of figures with the published table. If the figures differed, correct the data file first."""
    from .web import check_csrf
    check_csrf(request, csrf)
    if mid not in taxonomy.MATERIALS or data_group not in DATA_GROUPS or outcome not in ("matched", "corrected"):
        raise HTTPException(422, "bad request")
    if outcome == "corrected" and not note.strip():
        raise HTTPException(422, "Say what was corrected.")
    db.add(M.DataVerification(material_id=mid, data_group=data_group, source_doc=source_doc.strip(), outcome=outcome, note=note.strip(), reviewer=who))
    db.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/alternate/{mid}")
def alternate(mid: str, request: Request, country: str = Form(..., max_length=64), status: str = Form(...), evidence_url: str = Form(..., min_length=8, max_length=512),
              evidence_note: str = Form(..., min_length=10, max_length=1000), csrf: str = Form(""), who: str = Depends(reviewer), db: Session = Depends(get_db)):
    """Record that a listed producer is (or is not) a qualified alternate source, with evidence. Republishes so the score and chain reflect it."""
    from .web import check_csrf
    check_csrf(request, csrf)
    m = taxonomy.MATERIALS.get(mid)
    if not m or status not in ("qualified", "unqualified") or not evidence_url.startswith(("http://", "https://")):
        raise HTTPException(422, "bad request")
    if country not in {a["country"] for a in m["alternative_sources"]}:
        raise HTTPException(422, "That country is not a listed producer for this material.")
    db.add(M.AlternateSourceReview(material_id=mid, country=country, status=status, evidence_url=evidence_url.strip(),
                                   evidence_note=evidence_note.strip(), reviewer=who))
    db.commit()
    S.publish_all(db)
    return RedirectResponse("/admin", status_code=303)


@router.post("/signoff/{mid}")
def signoff(mid: str, request: Request, csrf: str = Form(""), who: str = Depends(reviewer), db: Session = Depends(get_db)):
    """Sign-off needs a recorded comparison of both the import and the production figures with the published table."""
    from .web import check_csrf
    check_csrf(request, csrf)
    m = db.get(M.Material, mid)
    if not m:
        raise HTTPException(404, "unknown material")
    done = {r[0] for r in db.execute(select(M.DataVerification.data_group).where(M.DataVerification.material_id == mid)).all()}
    missing = [g for g in ("import", "production") if g not in done]
    if missing:
        raise HTTPException(409, "Cannot sign off yet. Record a comparison with the published table for: " + ", ".join(missing) + ".")
    m.signed_off_by, m.signed_off_at = who, M.now()
    db.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/publish")
def publish_now(request: Request, csrf: str = Form(""), who: str = Depends(reviewer), db: Session = Depends(get_db)):
    from .web import check_csrf
    check_csrf(request, csrf)
    S.publish_all(db)
    return RedirectResponse("/admin", status_code=303)
