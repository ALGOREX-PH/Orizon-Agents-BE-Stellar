from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .routers import agents, flow, metrics, orchestrator, payments, pdax, stellar, tasks, trace
from .security import RateLimitMiddleware, RequestContextMiddleware
from .seed import seed_registry
from .state import state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    seed_registry()
    yield


class SecurityHeadersMiddleware:
    """Pure-ASGI middleware stamping baseline hardening headers on responses.

    Deliberately minimal for a JSON API: no CSP (nothing is rendered) and no
    HSTS (TLS terminates at Render's edge, which sets it).
    """

    _HEADERS = [
        (b"x-content-type-options", b"nosniff"),
        (b"referrer-policy", b"no-referrer"),
        (b"x-frame-options", b"DENY"),
    ]

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers") or []) + self._HEADERS
            await send(message)

        await self.app(scope, receive, send_with_headers)


app = FastAPI(
    title="Orizon Agents API",
    version="0.1.0",
    description="The orchestration layer for autonomous digital labor.",
    lifespan=lifespan,
)

# Added first → runs innermost: hardening headers land on every app response.
app.add_middleware(SecurityHeadersMiddleware)

# Registered before CORS so CORS wraps it and 429 responses still carry
# the Access-Control-Allow-Origin header the browser needs to read them.
app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # Accept every Vercel preview / production domain without needing to
    # re-list them in CORS_ORIGINS. Tighten this regex once the final prod
    # subdomain is known (e.g. r"^https://orizon-agents(-.*)?\.vercel\.app$").
    allow_origin_regex=r"https://.*\.vercel\.app",
    # The API is token/header-based — no cookies — so credentials stay off,
    # and only the methods/headers the frontend actually sends are allowed.
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["content-type", "authorization", "x-api-key"],
)

# Added last → runs outermost, so artifact/trace payloads (30–76 kB) leave the
# stack compressed while the rate limiter still sees the raw request.
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Outermost of all: every response — including 429s from the limiter and
# CORS rejections — carries an X-Request-ID, and the logged duration covers
# the full middleware stack.
app.add_middleware(RequestContextMiddleware)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log the full traceback server-side; never leak exception text to clients."""
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    # This handler runs on the OUTERMOST layer (ServerErrorMiddleware), so the
    # security-header, rate-limit, and CORS middleware never see the response.
    # Stamp the hardening headers — and the CORS header for known origins —
    # by hand, or browsers report an opaque CORS failure instead of letting
    # the frontend read this JSON envelope.
    headers = {
        "x-content-type-options": "nosniff",
        "referrer-policy": "no-referrer",
        "x-frame-options": "DENY",
    }
    origin = request.headers.get("origin")
    if origin and origin in settings.cors_origin_list:
        headers["access-control-allow-origin"] = origin
        headers["vary"] = "Origin"
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "internal server error"}},
        headers=headers,
    )


app.include_router(agents.router, prefix="/api")
app.include_router(orchestrator.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(trace.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(flow.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(stellar.router, prefix="/api")
app.include_router(pdax.router, prefix="/api")


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "orizon-agents", "status": "online"}


@app.get("/health")
async def health() -> dict[str, Any]:
    """Liveness probe — process is up and serving."""
    return {
        "status": "ok",
        "version": app.version,
        "uptime_seconds": round(time.time() - state.started_at, 1),
    }


@app.get("/readiness")
async def readiness() -> JSONResponse:
    """Readiness probe — reports which required Stellar settings are missing."""
    missing: list[str] = []
    if not settings.stellar_signing_key:
        missing.append("STELLAR_SIGNING_KEY")
    if not settings.stellar_rpc_url:
        missing.append("STELLAR_RPC_URL")
    if missing:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "missing": missing},
        )
    return JSONResponse(content={"status": "ready", "missing": []})
