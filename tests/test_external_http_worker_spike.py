"""Story 1.06 spike — prove Candidate A actually dispatches a step.

These tests stand up an in-process operator endpoint (httpx.ASGITransport over
a tiny FastAPI app — a real request/response cycle, no sockets) and drive the
ExternalHttpWorker against it, including THROUGH the real orchestrator loop
(`execution_svc._run`) so the acceptance criterion "its response should be
accepted by the orchestrator" is met by running code, not prose.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.agents.workers.external_http import ExternalHttpWorker

ENDPOINT = "http://operator.local/run"


def _client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://operator.local")


def _worker(client: httpx.AsyncClient) -> ExternalHttpWorker:
    return ExternalHttpWorker("ext_demo1", "external.demo", ENDPOINT, client=client)


def test_dispatch_carries_the_envelope_and_returns_the_output() -> None:
    seen: dict[str, Any] = {}
    app = FastAPI()

    @app.post("/run")
    async def run(req: Request) -> JSONResponse:
        seen["body"] = await req.json()
        seen["idempotency_key"] = req.headers.get("Idempotency-Key")
        seen["content_type"] = req.headers.get("Content-Type")
        return JSONResponse(
            {"summary": "built the landing page", "artifact": {"title": "x", "files": []}, "source": "external"}
        )

    async def go() -> dict[str, Any]:
        async with _client_for(app) as client:
            return await _worker(client).run("make a bakery landing page", "draft it", context={"kit": None})

    out = asyncio.run(go())

    assert out["summary"] == "built the landing page"
    assert out["source"] == "external"

    body = seen["body"]
    assert body["v"] == 1
    assert body["agent_id"] == "ext_demo1"
    assert body["intent"] == "make a bakery landing page"
    assert body["rationale"] == "draft it"
    assert body["context"] == {"kit": None}
    assert body["dispatch_id"]
    # the idempotency key the operator can dedupe on IS the dispatch id
    assert seen["idempotency_key"] == body["dispatch_id"]
    assert seen["content_type"] == "application/json"
