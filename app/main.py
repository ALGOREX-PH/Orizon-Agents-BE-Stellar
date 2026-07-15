from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .routers import agents, flow, metrics, orchestrator, payments, pdax, stellar, tasks, trace
from .security import RateLimitMiddleware
from .seed import seed_registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    seed_registry()
    yield


app = FastAPI(
    title="Orizon Agents API",
    version="0.1.0",
    description="The orchestration layer for autonomous digital labor.",
    lifespan=lifespan,
)

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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log the full traceback server-side; never leak exception text to clients."""
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "internal server error"}},
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
