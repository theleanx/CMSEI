"""Company layer routes: parts-list upload, what-if, supplier questionnaire, compliance screen, alerts, widget, validation, governance.
Uploaded parts lists are processed in memory and never stored. See the Privacy page."""
from __future__ import annotations
import json
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from . import api as api_mod, models as M
from .config import settings
from .db import get_db
from .engine import bom, compliance, taxonomy, validation
from .services import alerts, assess, company as C, pdf, snapshots as S
from .web import render, check_csrf, error_page

web = APIRouter()
api = APIRouter(prefix="/api/v1")
MAX_BODY = bom.MAX_BYTES + 200_000


def _scenario(material_id, country, cut, price) -> dict | None:
    if not material_id:
        return None
    p = None
    if price not in (None, ""):
        try:
            p = float(price)
        except ValueError:
            raise bom.BomError("The price rise must be a number, for example 20.")
        if not (0 <= p <= 1000):
            raise bom.BomError("The price rise must be between 0 and 1000 percent.")
    return {"material_id": material_id, "country": (country or "").strip()[:64] or None, "cut": cut, "price_shock_pct": p}


def _flags(dod, sec) -> dict:
    f = {}
    if dod in ("yes", "no"):
        f["defense"] = dod == "yes"
    if sec in ("yes", "no"):
        f["sec_filer"] = sec == "yes"
    return f


def _material_options():
    return sorted(((k, v["name"]) for k, v in taxonomy.MATERIALS.items()), key=lambda x: x[1])


# ------------------------------------------------------------------ web: company screen
@web.get("/company", response_class=HTMLResponse)
def company_page(request: Request):
    return render(request, "company.html", {"materials": _material_options(), "sectors": C.SECTORS, "max_mb": bom.MAX_BYTES // 1_000_000,
                                            "max_rows": bom.MAX_ROWS})


@web.get("/company/template.csv")
def template():
    return Response(C.template_csv(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="cmsei-parts-template.csv"'})


@web.post("/company/analyze", response_class=HTMLResponse)
def company_analyze(request: Request, file: UploadFile = File(...), csrf: str = Form(""), output: str = Form("screen", max_length=16),
                    company_name: str = Form("", max_length=80), sells_to_dod: str = Form("", max_length=4), sec_filer: str = Form("", max_length=4),
                    scenario_material: str = Form("", max_length=64), scenario_country: str = Form("", max_length=64),
                    scenario_cut: str = Form("full", max_length=8), price_shock_pct: str = Form("", max_length=8),
                    benchmark_sector: str = Form("", max_length=32), share_benchmark: str = Form("", max_length=4),
                    db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    raw = file.file.read(bom.MAX_BYTES + 1)
    try:
        res = C.run(db, raw, _flags(sells_to_dod, sec_filer), _scenario(scenario_material, scenario_country, scenario_cut, price_shock_pct))
    except bom.BomError as e:
        return render(request, "company.html", {"materials": _material_options(), "sectors": C.SECTORS, "error": str(e), "max_mb": bom.MAX_BYTES // 1_000_000,
                                                "max_rows": bom.MAX_ROWS}, 422)
    assess.track(db, "company_screen", method="upload")
    if output == "pdf":
        return Response(pdf.company_report(res, company_name.strip()), media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="cmsei-supply-exposure-screen.pdf"'})
    if output == "parts_csv":
        return Response(C.parts_csv(res), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="cmsei-parts-exposure.csv"'})
    if output == "questionnaire":
        scores, _ = C.score_map(db)
        return Response(C.questionnaire_csv(res, scores), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="cmsei-supplier-questionnaire.csv"'})
    bench = None
    if benchmark_sector in C.SECTORS and res["products"]:
        score = max(p["score"] for p in res["products"])
        shared = False
        if share_benchmark == "yes":
            shared = C.bench_add(db, benchmark_sector, score)
        bench = dict(C.bench_read(db, benchmark_sector, score), sector=C.SECTORS[benchmark_sector], shared=shared, score=score)
    return render(request, "company_result.html", {"r": C.public(res), "bench": bench, "company_name": company_name.strip()})


# ------------------------------------------------------------------ web: reference pages
@web.get("/validation", response_class=HTMLResponse)
def validation_page(request: Request):
    res = json.loads((taxonomy.DATA / "validation_result.json").read_text())
    return render(request, "validation.html", {"v": res, "reg": validation.registry(), "names": {k: v["name"] for k, v in taxonomy.MATERIALS.items()}})


@web.get("/compliance", response_class=HTMLResponse)
def compliance_page(request: Request):
    return render(request, "compliance.html", {"rules": list(compliance.RULES.values()), "version": compliance.VERSION, "reviewed": compliance.LAST_REVIEWED,
                                               "note": compliance.NOTE, "tariffs": compliance.TARIFFS_NOTE,
                                               "names": {k: v["name"] for k, v in taxonomy.MATERIALS.items()}})


@web.get("/governance", response_class=HTMLResponse)
def governance_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "governance.html", {"v": S.verification_status(db), "m": governance(db)})


def governance(db: Session) -> dict:
    return {"maintainer": settings.maintainer_name, "role": settings.maintainer_role, "contact": settings.contact,
            "verification": S.verification_status(db), "sign_offs": db.query(M.Material).filter(M.Material.signed_off_by.is_not(None)).count(),
            "policy": "A material shows 'reviewed' only after a person has compared its import and production figures with the published table and recorded it. "
                      "An alternate source earns credit only after a person records evidence that it is qualified."}


@web.get("/embed", response_class=HTMLResponse)
def embed_docs(request: Request):
    return render(request, "embed_docs.html", {"materials": _material_options(), "base": settings.base_url})


@web.get("/embed/materials/{mid}", response_class=HTMLResponse)
def embed_card(request: Request, mid: str, db: Session = Depends(get_db)):
    v = assess.material_view(db, mid)
    if not v:
        return PlainTextResponse("Not found", status_code=404)
    return render(request, "embed_card.html", {"v": v, "tier": v["snapshot"]["tier"], "mid": mid})


# ------------------------------------------------------------------ web: alerts
@web.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request):
    return render(request, "alerts.html", {"materials": _material_options(), "email_on": alerts.email_enabled()})


@web.post("/alerts/subscribe", response_class=HTMLResponse)
def alerts_subscribe(request: Request, channel: str = Form("", max_length=8), target: str = Form("", max_length=700), material_ids: list[str] = Form([]),
                     csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    try:
        r = alerts.subscribe(db, channel, target, material_ids)
    except alerts.AlertError as e:
        return render(request, "alerts.html", {"materials": _material_options(), "email_on": alerts.email_enabled(), "error": str(e)}, 422)
    return render(request, "alerts_done.html", {"r": r, "channel": channel, "names": {k: v["name"] for k, v in taxonomy.MATERIALS.items()}})


@web.get("/alerts/confirm/{token}", response_class=HTMLResponse)
def alerts_confirm(request: Request, token: str, db: Session = Depends(get_db)):
    ok = alerts.confirm(db, token)
    return render(request, "alerts_confirmed.html", {"ok": ok}, 200 if ok else 404)


@web.get("/alerts/manage/{token}", response_class=HTMLResponse)
def alerts_manage(request: Request, token: str, db: Session = Depends(get_db)):
    sub = alerts.by_manage_token(db, token)
    if not sub:
        return error_page(request, 404, "That manage link is not valid. It may have been used already.")
    return render(request, "alerts_manage.html", {"sub": sub, "token": token, "names": {k: v["name"] for k, v in taxonomy.MATERIALS.items()}})


@web.post("/alerts/manage/{token}/delete")
def alerts_delete(request: Request, token: str, csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    alerts.remove(db, token)
    return RedirectResponse("/alerts?removed=1", status_code=303)


# ------------------------------------------------------------------ API
async def _body(request: Request) -> bytes:
    raw = await request.body()
    if len(raw) > bom.MAX_BYTES:
        raise api_mod.ApiError(413, "too_large", f"Body larger than {bom.MAX_BYTES // 1_000_000} MB.")
    return raw


@api.get("/company/template.csv")
def api_template():
    return Response(C.template_csv(), media_type="text/csv")


@api.post("/company/analyze")
async def api_analyze(request: Request, db: Session = Depends(get_db), scenario_material: str | None = Query(default=None, max_length=64),
                      scenario_country: str | None = Query(default=None, max_length=64), scenario_cut: str = Query(default="full", max_length=8),
                      price_shock_pct: str | None = Query(default=None, max_length=8), sells_to_dod: str | None = Query(default=None, max_length=4),
                      sec_filer: str | None = Query(default=None, max_length=4)):
    """Body: the parts list as text/csv. Returns the analysis as JSON. Nothing is stored."""
    raw = await _body(request)
    try:
        res = C.run(db, raw, _flags(sells_to_dod or "", sec_filer or ""), _scenario(scenario_material, scenario_country, scenario_cut, price_shock_pct))
    except bom.BomError as e:
        raise api_mod.ApiError(422, "invalid_bom", str(e))
    return C.public(res)


@api.post("/company/questionnaire")
async def api_questionnaire(request: Request, db: Session = Depends(get_db)):
    raw = await _body(request)
    try:
        res = C.run(db, raw)
    except bom.BomError as e:
        raise api_mod.ApiError(422, "invalid_bom", str(e))
    scores, _ = C.score_map(db)
    return Response(C.questionnaire_csv(res, scores), media_type="text/csv")


@api.get("/validation")
def api_validation():
    return json.loads((taxonomy.DATA / "validation_result.json").read_text())


@api.get("/validation/registry")
def api_registry():
    return validation.registry()


@api.get("/compliance")
def api_compliance():
    return {"version": compliance.VERSION, "last_reviewed": compliance.LAST_REVIEWED, "note": compliance.NOTE, "tariffs": compliance.TARIFFS_NOTE,
            "rules": list(compliance.RULES.values())}


@api.get("/governance")
def api_governance(db: Session = Depends(get_db)):
    return governance(db)


class AlertIn(BaseModel):
    channel: str = Field(max_length=8)
    target: str = Field(max_length=700)
    material_ids: list[str] = Field(max_length=25)


@api.post("/alerts", status_code=201)
def api_alert_add(body: AlertIn, db: Session = Depends(get_db)):
    try:
        return alerts.subscribe(db, body.channel, body.target, body.material_ids)
    except alerts.AlertError as e:
        raise api_mod.ApiError(422, "alert_rejected", str(e))


@api.delete("/alerts/{token}", status_code=204)
def api_alert_del(token: str, db: Session = Depends(get_db)):
    if not alerts.remove(db, token):
        raise api_mod.ApiError(404, "not_found", "No subscription for that manage token.")
    return Response(status_code=204)
