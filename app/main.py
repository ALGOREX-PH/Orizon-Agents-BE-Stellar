from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import agents, flow, metrics, orchestrator, payments, stellar, tasks, trace
from .seed import seed_registry


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents.router, prefix="/api")
app.include_router(orchestrator.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(trace.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(flow.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(stellar.router, prefix="/api")


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "orizon-agents", "status": "online"}
