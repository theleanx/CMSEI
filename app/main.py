"""Application entry point: API v1 + server-rendered web app, security headers, rate limiting, privacy-safe logging."""
from __future__ import annotations
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, HTTPException as FHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
import pathlib

from .config import settings
from .db import engine, Base, SessionLocal
from . import models  # noqa: F401
from .logging_setup import setup as setup_logging
from .ratelimit import limiter
from .services import snapshots as S
from . import api, web, admin

log = logging.getLogger("mse")
BASE = pathlib.Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        S.ensure_materials(db)
        if not S.latest(db, next(iter(S.taxonomy.MATERIALS))):
            r = S.publish_all(db)
            log.info("initial snapshots published: %s", len(r["created"]))
    finally:
        db.close()
    yield


app = FastAPI(title="Critical Material Supply Exposure Index (CMSEI)", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", redoc_url=None,
              openapi_url="/api/openapi.json")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=[], allow_credentials=False)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")


def client_key(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    # The platform proxy appends the real client address last; earlier entries can be forged by the caller.
    return (xff.split(",")[-1].strip() if xff else (request.client.host if request.client else "?")) or "?"


@app.middleware("http")
async def guard(request: Request, call_next):
    t0 = time.time()
    path = request.url.path
    if not path.startswith("/static"):
        key = client_key(request)
        lim = settings.rate_assess_per_minute_ip if (request.method == "POST" and path in ("/assess", "/api/v1/assess")) else settings.rate_per_minute_ip
        if not limiter.allow(f"{key}:{'assess' if lim == settings.rate_assess_per_minute_ip else 'all'}", lim):
            return JSONResponse({"error": {"code": "rate_limited", "message": "Too many requests. Try again in a minute."}}, status_code=429,
                                headers={"Retry-After": "60"})
    try:
        resp = await call_next(request)
    except Exception:
        log.exception("unhandled error on %s %s", request.method, path)      # message only, no request data
        resp = JSONResponse({"error": {"code": "server_error", "message": "Something went wrong."}}, status_code=500)
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), interest-cohort=()"
    if settings.env == "production":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if path.startswith("/api/") or path.startswith("/admin"):
        resp.headers.setdefault("Cache-Control", "no-store" if request.method != "GET" or path.startswith("/admin") else "public, max-age=60")
    elif request.method != "GET":
        resp.headers["Cache-Control"] = "no-store"
    route = request.scope.get("route")
    log.info("%s %s %s %dms", request.method, getattr(route, "path", "unmatched"), resp.status_code, int((time.time() - t0) * 1000))
    return resp


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    # never echo the submitted value
    fields = sorted({".".join(str(p) for p in e["loc"][1:]) or "body" for e in exc.errors()})
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": {"code": "invalid_input", "message": "Invalid or missing fields: " + ", ".join(fields)}}, status_code=422)
    return web.error_page(request, 422, "That input was not valid.")


@app.exception_handler(StarletteHTTPException)
async def http_handler(request: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(exc.detail, status_code=exc.status_code, headers=getattr(exc, "headers", None))
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": {"code": "http_%d" % exc.status_code, "message": str(exc.detail)}}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))
    if exc.status_code == 401 and request.url.path.startswith("/admin"):
        return PlainTextResponse("Authentication required", status_code=401, headers=getattr(exc, "headers", None))
    return web.error_page(request, exc.status_code, "That page was not found." if exc.status_code == 404 else "Something went wrong.")


app.include_router(api.router)
app.include_router(admin.router)
app.include_router(web.router)
