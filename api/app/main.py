"""Point d'entrée de l'API VidGrab : routes, middlewares et gestion des erreurs."""
from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from .config import Settings
from .downloader import download_media, fetch_info, safe_name
from .errors import ApiError
from .security import RateLimiter, client_ip, parse_quality, prepare_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vidgrab")

API_PATHS = {"/health", "/info", "/download"}


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings.from_env()
    app = FastAPI(
        title="VidGrab API",
        docs_url="/docs" if cfg.enable_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if cfg.enable_docs else None,
    )

    # --- Protections ---------------------------------------------------------
    info_limiter = RateLimiter(cfg.rate_info_per_min, 60)
    download_limiter = RateLimiter(cfg.rate_download_per_min, 60)
    global_limiter = RateLimiter(cfg.global_downloads_per_hour, 3600)
    slots = threading.BoundedSemaphore(cfg.max_concurrent)

    def throttle(limiter: RateLimiter):
        def check(request: Request) -> None:
            if not limiter.allow(client_ip(request, cfg.trusted_proxy_hops)):
                raise ApiError(429, "Trop de requêtes, réessaie dans une minute.")

        return check

    @app.middleware("http")
    async def guard(request: Request, call_next):
        """Refuse les origines inconnues et ajoute les en-têtes de sécurité."""
        path = request.url.path
        origin = request.headers.get("origin")
        if path in API_PATHS and origin and origin not in cfg.allowed_origins:
            response = JSONResponse({"detail": "Origine non autorisée."}, status_code=403)
        else:
            response = await call_next(request)
        h = response.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["Referrer-Policy"] = "no-referrer"
        h["X-Frame-Options"] = "DENY"
        if path in API_PATHS:
            h["Cache-Control"] = "no-store"
            h["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if request.headers.get("x-forwarded-proto") == "https":
            h["Strict-Transport-Security"] = "max-age=15552000"
        return response

    # Ajouté en dernier = exécuté en premier (gère aussi les réponses d'erreur).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.allowed_origins),
        allow_methods=["GET"],
        allow_headers=[],
        expose_headers=["Content-Disposition", "Content-Length"],
    )

    # --- Erreurs : jamais de détails internes renvoyés -------------------------
    @app.exception_handler(ApiError)
    async def on_api_error(_: Request, exc: ApiError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def on_invalid(_: Request, exc: RequestValidationError):
        return JSONResponse({"detail": "Requête invalide."}, status_code=422)

    @app.exception_handler(Exception)
    async def on_crash(_: Request, exc: Exception):
        log.exception("Erreur inattendue")
        return JSONResponse({"detail": "Erreur interne du serveur."}, status_code=500)

    # --- Routes -----------------------------------------------------------------
    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/info", dependencies=[Depends(throttle(info_limiter))])
    def info(url: str = Query(..., max_length=500)):
        clean_url, platform = prepare_url(url)
        return {"platform": platform, **fetch_info(cfg, clean_url)}

    @app.get("/download", dependencies=[Depends(throttle(download_limiter))])
    def download(
        url: str = Query(..., max_length=500),
        fmt: str = Query("mp4", alias="format", pattern="^(mp4|mp3)$"),
        quality: str = Query("720p", max_length=12),
    ):
        clean_url, platform = prepare_url(url)
        level = parse_quality(fmt, quality)
        if not global_limiter.allow("global"):
            raise ApiError(503, "Limite horaire du service atteinte, réessaie plus tard.")
        if not slots.acquire(blocking=False):
            raise ApiError(503, "Serveur occupé, réessaie dans un instant.")
        try:
            media = download_media(cfg, clean_url, fmt, level)
        finally:
            slots.release()
        log.info("download ok platform=%s format=%s quality=%s", platform, fmt, level)
        return FileResponse(
            media.path,
            filename=f"{safe_name(media.title)}.{media.ext}",
            media_type=media.media_type,
            background=BackgroundTask(shutil.rmtree, media.tmpdir, ignore_errors=True),
        )

    # Usage local : sert l'interface (dossier docs/) sur http://localhost:8000
    if cfg.serve_front:
        front = Path(__file__).resolve().parents[2] / "docs"
        if front.is_dir():
            app.mount("/", StaticFiles(directory=front, html=True), name="front")

    return app


app = create_app()
