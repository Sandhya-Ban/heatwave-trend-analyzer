from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import date
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import exports
from .config import Settings
from .errors import DataQualityError, ProviderError, StorageError
from .provider import OpenMeteoProvider
from .ratelimit import RateLimiter
from .service import AnalysisParams, AnalysisService
from .store import Store
from .synthetic import SyntheticProvider

log = logging.getLogger("api")
SUPPORTED_HAZARDS = ("heatwave", "heavy_rainfall", "drought")
MIN_SPAN_YEARS = 10
MAX_BOX_DEG = 10.0
_CTRL = re.compile(r"[\x00-\x1f\x7f<>]")


def create_app(settings: Optional[Settings] = None, provider=None, store: Optional[Store] = None,
               today=date.today) -> FastAPI:
    cfg = settings or Settings.from_env()
    store = store or Store(cfg.mongodb_uri, cfg.mongodb_db, cfg.cache_ttl_days)
    if provider is None:
        provider = SyntheticProvider() if cfg.synthetic else OpenMeteoProvider(cfg.provider_timeout_s, cfg.provider_retries)
    service = AnalysisService(store, provider, cache_ttl_days=cfg.cache_ttl_days, fresh_ttl_hours=cfg.fresh_data_ttl_hours,
                              max_concurrent_fetches=cfg.max_concurrent_fetches, today=today)
    limiter = RateLimiter(cfg.rate_window_s)
    geo_cache: dict[str, tuple[float, list]] = {}
    geo_lock = threading.Lock()

    app = FastAPI(title="Climate Hazard Trend Analyzer", docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")
    if cfg.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(cfg.cors_origins), allow_methods=["GET"], allow_headers=["*"])

    # ---------------- middleware ----------------
    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and request.method != "OPTIONS":
            ip = request.client.host if request.client else "unknown"
            if cfg.trust_proxy:
                xff = request.headers.get("x-forwarded-for", "")
                ip = xff.split(",")[0].strip() or ip
            heavy = path.startswith(("/api/analysis", "/api/export"))
            ok, retry = limiter.check(ip, "heavy" if heavy else "general",
                                      cfg.rate_limit_heavy if heavy else cfg.rate_limit_general)
            if not ok:
                return JSONResponse({"detail": "Rate limit exceeded. Please slow down."}, status_code=429,
                                    headers={"Retry-After": str(retry)})
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; img-src 'self' data: https://*.tile.openstreetmap.org; "
                                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                                "font-src 'self' https://fonts.gstatic.com; connect-src 'self'")
        return resp

    # ---------------- error handling (never leak internals) ----------------
    @app.exception_handler(ProviderError)
    async def _prov(_: Request, exc: ProviderError):
        log.warning("provider error: %s", exc)
        return JSONResponse({"detail": f"Weather data provider problem: {exc}"}, status_code=502)

    @app.exception_handler(DataQualityError)
    async def _dq(_: Request, exc: DataQualityError):
        return JSONResponse({"detail": f"Data not usable: {exc}"}, status_code=422)

    @app.exception_handler(StorageError)
    async def _st(_: Request, exc: StorageError):
        return JSONResponse({"detail": "Storage temporarily unavailable. Try again shortly."}, status_code=503)

    @app.exception_handler(Exception)
    async def _any(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    # ---------------- input validation ----------------
    def parse_params(
        lat: Optional[float] = Query(None, ge=-90, le=90), lon: Optional[float] = Query(None, ge=-180, le=180),
        min_lat: Optional[float] = Query(None, ge=-90, le=90), max_lat: Optional[float] = Query(None, ge=-90, le=90),
        min_lon: Optional[float] = Query(None, ge=-180, le=180), max_lon: Optional[float] = Query(None, ge=-180, le=180),
        start_year: int = Query(1991, ge=1940, le=2100), end_year: int = Query(2020, ge=1940, le=2100),
        hazard: str = Query("heatwave", max_length=32),
        percentile: float = Query(95.0, ge=80, le=99.5), min_days: int = Query(3, ge=2, le=10),
    ) -> AnalysisParams:
        if hazard not in SUPPORTED_HAZARDS:
            raise HTTPException(400, f"Unsupported hazard '{hazard[:32]}'. Supported: {', '.join(SUPPORTED_HAZARDS)}")
        box = [min_lat, max_lat, min_lon, max_lon]
        has_pt, has_box = (lat is not None or lon is not None), any(v is not None for v in box)
        if has_pt and has_box:
            raise HTTPException(422, "Provide either lat/lon or a bounding box, not both")
        bbox = None
        if has_box:
            if any(v is None for v in box):
                raise HTTPException(422, "A bounding box needs min_lat, max_lat, min_lon and max_lon")
            if min_lat >= max_lat or min_lon >= max_lon:
                raise HTTPException(422, "Bounding box must have min < max (boxes crossing the antimeridian are not supported)")
            if max_lat - min_lat > MAX_BOX_DEG or max_lon - min_lon > MAX_BOX_DEG:
                raise HTTPException(422, f"Bounding box too large (max {MAX_BOX_DEG:g} degrees per side)")
            bbox = (min_lat, max_lat, min_lon, max_lon)
            lat, lon = (min_lat + max_lat) / 2, (min_lon + max_lon) / 2
        elif lat is None or lon is None:
            raise HTTPException(422, "Provide lat and lon (or a bounding box)")
        this_year = today().year
        if end_year > this_year:
            raise HTTPException(422, f"end_year cannot be after {this_year}")
        if end_year - start_year + 1 < MIN_SPAN_YEARS:
            raise HTTPException(422, f"Time range must span at least {MIN_SPAN_YEARS} years for a meaningful trend")
        pct, md = round(percentile, 1), min_days
        if hazard == "drought":
            pct, md = 0.0, 0                # fixed SPI-3 definition: percentile / min-days do not apply
        elif hazard == "heavy_rainfall":
            md = 0                          # single-day events: min-days does not apply
        return AnalysisParams(round(lat, 2), round(lon, 2), start_year, end_year, pct, md, bbox, hazard)

    # ---------------- routes ----------------
    @app.get("/api/health")
    def health():
        return {"status": "ok", "database": "up" if store.ping() else "down", "synthetic": cfg.synthetic}

    @app.get("/api/hazards")
    def hazards_list():
        return {"hazards": [{"id": "heatwave", "label": "Heatwave", "default": True},
                            {"id": "heavy_rainfall", "label": "Heavy rainfall", "default": False},
                            {"id": "drought", "label": "Drought", "default": False}]}

    @app.get("/api/geocode")
    def geocode(q: str = Query(..., min_length=2, max_length=80)):
        term = _CTRL.sub("", q).strip()
        if len(term) < 2:
            raise HTTPException(422, "Search text is too short")
        key, now = term.lower(), time.time()
        with geo_lock:
            hit = geo_cache.get(key)
            if hit and now - hit[0] < 86400:
                return {"results": hit[1]}
        res = provider.geocode(term)
        with geo_lock:
            if len(geo_cache) > 500:
                geo_cache.clear()
            geo_cache[key] = (now, res)
        return {"results": res}

    @app.get("/api/analysis")
    def analysis(p: AnalysisParams = Depends(parse_params)):
        return service.get_analysis(p)

    @app.get("/api/export/csv")
    def export_csv(kind: str = Query("yearly", pattern="^(yearly|events)$"), p: AnalysisParams = Depends(parse_params)):
        body = exports.to_csv(service.get_analysis(p), kind)
        name = f"{p.hazard}_{kind}_{p.lat}_{p.lon}_{p.start_year}-{p.end_year}.csv"
        return Response(body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/export/pdf")
    def export_pdf(p: AnalysisParams = Depends(parse_params)):
        body = exports.to_pdf(service.get_analysis(p))
        name = f"{p.hazard}_report_{p.lat}_{p.lon}_{p.start_year}-{p.end_year}.pdf"
        return Response(body, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    if cfg.frontend_dist and os.path.isdir(cfg.frontend_dist):
        app.mount("/", StaticFiles(directory=cfg.frontend_dist, html=True), name="frontend")
    return app


def app_factory() -> FastAPI:   # uvicorn app.main:app_factory --factory
    logging.basicConfig(level=logging.INFO)
    return create_app()
