from __future__ import annotations

import asyncio
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.utils import is_body_allowed_for_status_code
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .pdax.client import aclose_pdax_client
from .routers import agents, flow, metrics, orchestrator, payments, pdax, stellar, tasks, trace
from .security import RateLimitMiddleware, RequestContextMiddleware, request_id_var
from .seed import seed_registry
from .services import execution_svc
from .state import state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    seed_registry()
    # Bound the default executor: asyncio.to_thread otherwise sizes it to
    # min(32, cpu_count + 4) from the HOST's core count, while Render grants
    # this container only a small CPU share — 8 threads comfortably cover the
    # blocking Soroban SDK calls without oversubscribing the worker.
    executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="soroban")
    asyncio.get_running_loop().set_default_executor(executor)
    yield
    # Drain in-flight background executions: a bounded grace window to let
    # them finish, then cancel stragglers and reap the cancellations so the
    # process exits without "task was destroyed but it is pending" noise.
    pending = {t for t in execution_svc._background_tasks if not t.done()}
    if pending:
        _, pending = await asyncio.wait(pending, timeout=15)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.wait(pending, timeout=5)
    await aclose_pdax_client()
    executor.shutdown(wait=False)


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
    openapi_tags=[
        {"name": "agents", "description": "Registered agents and their skills, pricing, and reputation."},
        {"name": "orchestrator", "description": "Decompose a goal into a plan and execute it across agents."},
        {"name": "tasks", "description": "Task history, status, and produced artifacts."},
        {"name": "trace", "description": "Per-task execution traces, polled or streamed."},
        {"name": "metrics", "description": "Aggregate network metrics for the dashboard."},
        {"name": "flow", "description": "Agent-graph flow layout consumed by the frontend visualizer."},
        {"name": "payments", "description": "x402 payment challenges and settlement."},
        {"name": "stellar", "description": "Soroban contract reads, unsigned-XDR builds, and signed-XDR submits."},
        {"name": "pdax", "description": "PDAX PHP-to-crypto on/off-ramp: trade, funding, withdrawals, webhooks."},
    ],
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

# Details that are already machine-readable tokens ("invalid_api_key",
# "build_failed") are promoted to the envelope's error code as-is.
_SNAKE_TOKEN = re.compile(r"[a-z][a-z0-9]*(_[a-z0-9]+)*")


def _error_envelope(detail: Any, code: str, message: str) -> dict[str, Any]:
    """Unified error body: the legacy FastAPI "detail" key (unchanged, so
    existing clients keep working) plus an "error" object carrying a stable
    snake_case code, a human message, and the request id for support."""
    return {
        "detail": detail,
        "error": {"code": code, "message": message, "request_id": request_id_var.get()},
    }


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    """Emit HTTPExceptions in the unified envelope, preserving FastAPI's
    default semantics: same status, same headers, same "detail" value, and
    no body at all for statuses that must not carry one (204/304)."""
    headers = getattr(exc, "headers", None)
    if not is_body_allowed_for_status_code(exc.status_code):
        return Response(status_code=exc.status_code, headers=headers)
    detail = exc.detail
    if isinstance(detail, str) and _SNAKE_TOKEN.fullmatch(detail):
        code, message = detail, detail.replace("_", " ")
    else:
        try:
            code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
        except ValueError:
            code = "http_error"
        message = detail if isinstance(detail, str) else "request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_envelope(jsonable_encoder(detail), code, message),
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Same 422 body FastAPI emits by default, plus the "error" object."""
    return JSONResponse(
        status_code=422,
        content=_error_envelope(
            jsonable_encoder(exc.errors()), "validation_error", "request validation failed"
        ),
    )


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
