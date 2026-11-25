"""Server-rendered web app (spec part 10). No JavaScript is required for any task."""
from __future__ import annotations
import hmac
import pathlib
import secrets
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import models as M, api as api_mod
from .config import settings
from .db import get_db
from .engine import explain, recommend, simulator, taxonomy, scoring as sc
from .services import assess, sessions, snapshots as S, pdf

BASE = pathlib.Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
router = APIRouter()

TIER_CLASS = {"Low": "low", "Moderate": "mod", "High": "high", "Critical": "crit"}
TIER_BLURB = {
    "Low": "Concentration and substitution factors point to low market-level exposure.",
    "Moderate": "Some concentration or substitution difficulty. Worth watching.",
    "High": "Supply is concentrated, or hard to replace, or both.",
    "Critical": "Very high concentration with few alternatives.",
}
templates.env.globals.update(
    tier_class=TIER_CLASS, tier_blurb=TIER_BLURB, settings=settings, REGION_CHOICES=recommend.REGION_CHOICES,
    VOLUME_CHOICES=recommend.VOLUME_CHOICES, SCENARIO_FAMILIES=simulator.FAMILIES, EVENT_OPTIONS=simulator.EVENT_OPTIONS,
    round_score=sc.round_score, taxonomy_version=taxonomy.TAXONOMY_VERSION, source_vintage=taxonomy.SOURCE_VINTAGE,
)


def _csrf(request: Request) -> tuple[str, bool]:
    t = request.cookies.get("mse_csrf")
    if t and len(t) >= 20:
        return t, False
    return secrets.token_urlsafe(24), True


def render(request: Request, name: str, ctx: dict | None = None, status: int = 200, session_cookie: str | None = None):
    token, new = _csrf(request)
    ctx = dict(ctx or {})
    ctx.update(request=request, csrf=token, path=request.url.path)
    resp = templates.TemplateResponse(request, name, ctx, status_code=status)
    if new:
        resp.set_cookie("mse_csrf", token, httponly=True, samesite="strict", secure=settings.secure_cookies, max_age=86400 * 30)
    if session_cookie:
        resp.set_cookie("mse_session", session_cookie, httponly=True, samesite="lax", secure=settings.secure_cookies,
                        max_age=86400 * settings.session_days)
    return resp


def check_csrf(request: Request, token: str) -> None:
    c = request.cookies.get("mse_csrf", "")
    if not c or not token or not hmac.compare_digest(c, token):
        from fastapi import HTTPException
        raise HTTPException(403, "Form expired. Reload the page and try again.")


def error_page(request: Request, status: int, message: str):
    return render(request, "error.html", {"message": message, "status": status}, status)


def _session(db, request):
    return sessions.get(db, request.cookies.get("mse_session"))


def _tier_rank(db):
    rows = [r for r in (api_mod._row(db, mid) for mid in taxonomy.MATERIALS) if r]
    rows.sort(key=lambda r: -r["score"])
    return rows


# ---------- home and assessment ----------
@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    return render(request, "index.html", {"top": _tier_rank(db)[:6], "total": len(taxonomy.MATERIALS)})


@router.post("/assess", response_class=HTMLResponse)
def assess_form(request: Request, material_description: str = Form("", max_length=300), material_id: str = Form("", max_length=64),
                sourcing_region: str = Form("", max_length=16), volume_tier: str = Form("", max_length=16), csrf: str = Form(""),
                db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    region = sourcing_region if sourcing_region in recommend.REGION_KEYS else None
    volume = volume_tier if volume_tier in recommend.VOLUME_KEYS else None
    sh = _session(db, request)
    method, conf = "dropdown", None
    if material_id:
        mid = material_id if material_id in taxonomy.MATERIALS else None
    elif material_description.strip():
        cls = assess.classify_text(db, material_description)
        method, conf, mid = cls["method"], cls["confidence"], cls["resolved"]
        if not mid:
            assess.track(db, "classifier_low_confidence" if cls["candidates"] else "classifier_unresolved", method=method, session_hash=sh)
            return render(request, "choose.html", {"candidates": [(c, taxonomy.MATERIALS[c]["name"]) for c in cls["candidates"]],
                                                   "region": region or "", "volume": volume or "",
                                                   "all": sorted(((k, v["name"]) for k, v in taxonomy.MATERIALS.items()), key=lambda x: x[1])})
    else:
        return error_page(request, 422, "Describe a material or pick one from the list.")
    if not mid:
        return error_page(request, 422, "Unknown material.")
    return _result(request, db, mid, region, volume, record=True, method=method, sh=sh, personalized=bool(region or volume))


def _result(request, db, mid, region, volume, record=False, method=None, sh=None, personalized=False, extra=None):
    v = assess.material_view(db, mid, region, volume, record=record, method=method, session_hash=sh)
    if not v:
        return error_page(request, 404, "No published score for this material yet.")
    on_watch = False
    if sh:
        on_watch = db.execute(select(M.Watchlist.id).where(M.Watchlist.session_hash == sh, M.Watchlist.material_id == mid)).first() is not None
    ctx = dict(v, mid=mid, region=region or "", volume=volume or "", personalized=personalized, on_watch=on_watch,
               just_assessed=record, tier=v["snapshot"]["tier"], u=v["snapshot"]["uncertainty"], simulation=None)
    ctx.update(extra or {})
    return render(request, "result.html", ctx)


@router.get("/materials", response_class=HTMLResponse)
def materials_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    rows = _tier_rank(db)
    if q.strip():
        ql = q.strip().lower()[:60]
        rows = [r for r in rows if ql in r["name"].lower() or any(ql in s for s in taxonomy.MATERIALS[r["id"]]["synonyms"])]
    return render(request, "materials.html", {"rows": rows, "q": q[:60]})


@router.get("/materials/{mid}", response_class=HTMLResponse)
def material_page(request: Request, mid: str, db: Session = Depends(get_db)):
    if mid not in taxonomy.MATERIALS:
        return error_page(request, 404, "That material is not tracked.")
    return _result(request, db, mid, None, None, sh=_session(db, request))


@router.post("/materials/{mid}", response_class=HTMLResponse)
def material_personalize(request: Request, mid: str, sourcing_region: str = Form("", max_length=16), volume_tier: str = Form("", max_length=16),
                         csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    if mid not in taxonomy.MATERIALS:
        return error_page(request, 404, "That material is not tracked.")
    region = sourcing_region if sourcing_region in recommend.REGION_KEYS else None
    volume = volume_tier if volume_tier in recommend.VOLUME_KEYS else None
    return _result(request, db, mid, region, volume, sh=_session(db, request), personalized=bool(region or volume))


@router.post("/materials/{mid}/simulate", response_class=HTMLResponse)
def simulate_page(request: Request, mid: str, family: str = Form("", max_length=32), option: str = Form("", max_length=16),
                  sourcing_region: str = Form("", max_length=16), volume_tier: str = Form("", max_length=16), csrf: str = Form(""),
                  db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    region = sourcing_region if sourcing_region in recommend.REGION_KEYS else None
    volume = volume_tier if volume_tier in recommend.VOLUME_KEYS else None
    if family not in simulator.FAMILIES:
        return error_page(request, 422, "Pick a scenario.")
    try:
        sim = assess.scenario_view(db, mid, family, option or None, region, volume)
    except ValueError:
        return error_page(request, 422, "That option does not belong to this scenario.")
    if not sim:
        return error_page(request, 404, "That material is not tracked.")
    return _result(request, db, mid, region, volume, sh=_session(db, request), personalized=bool(region or volume), extra={"simulation": sim})


@router.get("/materials/{mid}/report.pdf")
def report_pdf(mid: str, db: Session = Depends(get_db)):
    v = assess.material_view(db, mid)
    if not v:
        return PlainTextResponse("Not found", status_code=404)
    return Response(pdf.material_report(v["material"], v["snapshot"], v["recommendations"]), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="exposure-{mid}.pdf"'})


# ---------- sectors ----------
@router.get("/sectors", response_class=HTMLResponse)
def sectors_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "sectors.html", {"sectors": api_mod._sector_rows(db), "list_status": taxonomy.SECTORS["status"],
                                            "list_version": taxonomy.SECTORS["list_version"], "names": {k: v["name"] for k, v in taxonomy.MATERIALS.items()}})


@router.get("/sectors/{sid}", response_class=HTMLResponse)
def sector_page(request: Request, sid: str, db: Session = Depends(get_db)):
    for r in api_mod._sector_rows(db):
        if r["id"] == sid:
            members = [x for x in (api_mod._row(db, m) for m in r["materials"]) if x]
            return render(request, "sector.html", {"s": r, "members": sorted(members, key=lambda x: -x["score"]),
                                                   "names": {k: v["name"] for k, v in taxonomy.MATERIALS.items()},
                                                   "list_status": taxonomy.SECTORS["status"]})
    return error_page(request, 404, "Unknown sector.")


# ---------- watchlist ----------
@router.get("/watchlist", response_class=HTMLResponse)
def watchlist_page(request: Request, db: Session = Depends(get_db)):
    sh = _session(db, request)
    items, changes = [], []
    if sh:
        items = api_mod._wl_rows(db, sh)
        changes = db.execute(select(M.WatchlistEvent).join(M.Watchlist, M.Watchlist.id == M.WatchlistEvent.watchlist_id)
                             .where(M.Watchlist.session_hash == sh).order_by(M.WatchlistEvent.id.desc()).limit(50)).scalars().all()
    return render(request, "watchlist.html", {"items": items, "changes": changes, "has_session": bool(sh)})


@router.post("/watchlist/add")
def watchlist_add(request: Request, material_id: str = Form("", max_length=64), alert_threshold: str = Form("", max_length=6),
                  csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    if material_id not in taxonomy.MATERIALS:
        return error_page(request, 404, "Unknown material.")
    sh = _session(db, request)
    cookie = None
    if not sh:
        cookie = sessions.create(db)
        sh = sessions.get(db, cookie)
    n = db.execute(select(M.Watchlist).where(M.Watchlist.session_hash == sh)).scalars().all()
    if not any(w.material_id == material_id for w in n):
        if len(n) >= settings.max_watchlist:
            return error_page(request, 409, f"Watchlist limit is {settings.max_watchlist}.")
        sn = S.latest(db, material_id)
        db.add(M.Watchlist(session_hash=sh, material_id=material_id, last_seen_snapshot_id=sn.id if sn else None))
        db.commit()
    resp = RedirectResponse("/watchlist", status_code=303)
    if cookie:
        resp.set_cookie("mse_session", cookie, httponly=True, samesite="lax", secure=settings.secure_cookies, max_age=86400 * settings.session_days)
    return resp


@router.post("/watchlist/remove")
def watchlist_remove(request: Request, material_id: str = Form("", max_length=64), csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    sh = _session(db, request)
    if sh:
        w = db.execute(select(M.Watchlist).where(M.Watchlist.session_hash == sh, M.Watchlist.material_id == material_id)).scalars().first()
        if w:
            db.query(M.WatchlistEvent).filter(M.WatchlistEvent.watchlist_id == w.id).delete()
            db.delete(w)
            db.commit()
    return RedirectResponse("/watchlist", status_code=303)


@router.post("/watchlist/seen")
def watchlist_seen(request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    sh = _session(db, request)
    if sh:
        ids = [w.id for w in db.execute(select(M.Watchlist).where(M.Watchlist.session_hash == sh)).scalars()]
        if ids:
            db.query(M.WatchlistEvent).filter(M.WatchlistEvent.watchlist_id.in_(ids), M.WatchlistEvent.seen_at.is_(None)).update(
                {"seen_at": M.now()}, synchronize_session=False)
            db.commit()
    return RedirectResponse("/watchlist", status_code=303)


@router.post("/session/delete")
def session_delete(request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    sh = _session(db, request)
    if sh:
        sessions.delete_all(db, sh)
    resp = RedirectResponse("/watchlist?deleted=1", status_code=303)
    resp.delete_cookie("mse_session")
    return resp


# ---------- corrections ----------
@router.get("/corrections", response_class=HTMLResponse)
def corrections_page(request: Request, material: str = "", sent: str = "", db: Session = Depends(get_db)):
    rows = db.execute(select(M.Correction).order_by(M.Correction.id.desc()).limit(100)).scalars().all()
    return render(request, "corrections.html", {"rows": rows, "material": material if material in taxonomy.MATERIALS else "", "sent": bool(sent),
                                                "mats": sorted(((k, v["name"]) for k, v in taxonomy.MATERIALS.items()), key=lambda x: x[1])})


@router.post("/corrections")
def corrections_submit(request: Request, material_id: str = Form("", max_length=64), item: str = Form("", max_length=128),
                       proposed_value: str = Form("", max_length=255), source_link: str = Form("", max_length=512),
                       note: str = Form("", max_length=1000), csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    if material_id not in taxonomy.MATERIALS or len(item.strip()) < 2 or not proposed_value.strip() or not source_link.lower().startswith(("http://", "https://")):
        return error_page(request, 422, "Pick a material, name the item, give the proposed value and a source link that starts with http.")
    db.add(M.Correction(material_id=material_id, item=item.strip(), proposed_value=proposed_value.strip(), source_link=source_link.strip(), note=note.strip()))
    db.commit()
    return RedirectResponse("/corrections?sent=1", status_code=303)


# ---------- static pages ----------
def _static(name):
    def view(request: Request, db: Session = Depends(get_db)):
        ctx = {}
        if name == "status.html":
            ctx["st"] = api_mod.data_status(db)
        if name == "events.html":
            ctx["events"] = db.execute(select(M.EventRecord).order_by(M.EventRecord.id.desc()).limit(200)).scalars().all()
            ctx["expl"] = {e.id: explain.explain_record(e) for e in ctx["events"]}
        if name == "methodology.html":
            ctx["m"] = api_mod.methodology()
            import json as _json
            ctx["val"] = _json.loads((taxonomy.DATA / "validation_result.json").read_text())
        return render(request, name, ctx)
    return view


for path, tpl in [("/methodology", "methodology.html"), ("/privacy", "privacy.html"), ("/terms", "terms.html"), ("/status", "status.html"),
                  ("/events", "events.html"), ("/accessibility", "accessibility.html")]:
    router.add_api_route(path, _static(tpl), methods=["GET"], response_class=HTMLResponse)


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return f"User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {settings.base_url}/sitemap.xml\n"


@router.get("/sitemap.xml")
def sitemap():
    urls = ["/", "/materials", "/sectors", "/company", "/validation", "/compliance", "/governance", "/alerts", "/embed", "/methodology", "/privacy", "/terms", "/status", "/events", "/corrections", "/accessibility"] + \
           [f"/materials/{m}" for m in taxonomy.MATERIALS]
    body = "".join(f"<url><loc>{settings.base_url}{u}</loc></url>" for u in urls)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
                    media_type="application/xml")
