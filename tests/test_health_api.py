"""The proxy-reachable liveness probe. The frontend only ever sees `/api/*`,
so `/api/health` must mirror the root `/health` body exactly and carry the
same rate-limit and access-log exemptions."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.config import SERVICE_VERSION
from app.security import RateLimitMiddleware


def test_api_health_probe(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == SERVICE_VERSION


def test_api_health_matches_root_health(client):
    """Both routes render the same shared payload — no drift, ever."""
    root = client.get("/health").json()
    proxied = client.get("/api/health").json()
    assert proxied.keys() == root.keys()
    assert proxied["status"] == root["status"]
    assert proxied["version"] == root["version"]


def test_api_health_carries_no_rate_limit_headers(client):
    """Exempt paths skip the limiter entirely, so no quota headers are
    stamped — a monitor polling here never consumes the caller's budget."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert "x-ratelimit-limit" not in r.headers
    assert "x-ratelimit-remaining" not in r.headers


def test_rate_limiter_exempts_api_health():
    async def ok(request):
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/api/health", ok)])
    limited = TestClient(RateLimitMiddleware(inner, limit=1, window_seconds=60))
    for _ in range(5):
        assert limited.get("/api/health").status_code == 200


def test_api_health_is_not_access_logged(client, caplog):
    """Same treatment the root probe gets: the id header is still echoed,
    but probe traffic stays out of the access log."""
    with caplog.at_level(logging.INFO, logger="app.security"):
        r = client.get("/api/health", headers={"X-Request-ID": "probe-rid-1"})
    assert r.status_code == 200
    assert r.headers["x-request-id"] == "probe-rid-1"
    assert not [rec for rec in caplog.records if rec.name == "app.security" and "/api/health" in rec.getMessage()]
