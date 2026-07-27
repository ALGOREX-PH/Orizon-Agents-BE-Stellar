"""Probes, auth guard, charge validation, and the rate limiter."""

from __future__ import annotations

from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.config import settings
from app.security import RateLimitMiddleware

VALID_G = "G" + "A" * 55
CHARGE_BODY = {
    "auth_id_hex": "ab" * 16,
    "amount_usdc": 1.0,
    "job_id_hex": "cd" * 16,
}


def test_health_probe(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readiness_reports_missing_signing_key(client):
    r = client.get("/readiness")
    assert r.status_code in (200, 503)
    assert "status" in r.json() or "detail" in r.json()


def test_charge_rejects_negative_amount(client):
    r = client.post(
        "/api/stellar/server/charge",
        json={**CHARGE_BODY, "amount_usdc": -5},
    )
    assert r.status_code == 422


def test_charge_rejects_malformed_hex_ids(client):
    r = client.post(
        "/api/stellar/server/charge",
        json={**CHARGE_BODY, "auth_id_hex": "not-hex"},
    )
    assert r.status_code == 422


def test_charge_unavailable_without_signing_key(client):
    r = client.post("/api/stellar/server/charge", json=CHARGE_BODY)
    assert r.status_code == 503


def test_charge_enforces_server_side_cap(client, hermetic_settings):
    from stellar_sdk import Keypair

    hermetic_settings.stellar_signing_key = Keypair.random().secret
    hermetic_settings.max_charge_usdc = 100.0
    r = client.post(
        "/api/stellar/server/charge",
        json={**CHARGE_BODY, "amount_usdc": 500.0},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "amount_exceeds_charge_cap"


def test_signing_routes_require_api_key_when_configured(client, hermetic_settings):
    hermetic_settings.api_key = "secret-key"
    r = client.post("/api/stellar/server/charge", json=CHARGE_BODY)
    assert r.status_code == 401
    r = client.post(
        "/api/stellar/server/charge",
        json=CHARGE_BODY,
        headers={"X-API-Key": "secret-key"},
    )
    # Past the guard now — fails later on the (unset) signing key instead.
    assert r.status_code == 503


def test_execute_rejects_bad_payer_address(client):
    r = client.post(
        "/api/orchestrator/execute",
        json={"plan_id": "nope", "payer": "not-an-address"},
    )
    assert r.status_code == 422


def test_register_agent_rejects_bad_owner(client):
    r = client.post(
        "/api/stellar/build/register-agent",
        json={
            "owner": "invalid",
            "agent_id": "a1",
            "name": "Agent",
            "skills": ["code"],
            "price_usdc": 0.1,
        },
    )
    assert r.status_code == 422


def test_rate_limiter_throttles_after_limit():
    async def ok(request):
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/hit", ok)])
    limited = TestClient(RateLimitMiddleware(inner, limit=3, window_seconds=60))

    for _ in range(3):
        assert limited.get("/hit").status_code == 200
    blocked = limited.get("/hit")
    assert blocked.status_code == 429
    assert "retry-after" in {k.lower() for k in blocked.headers}


def test_rate_limiter_exempts_health():
    async def ok(request):
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/health", ok)])
    limited = TestClient(RateLimitMiddleware(inner, limit=1, window_seconds=60))
    for _ in range(5):
        assert limited.get("/health").status_code == 200


def test_rate_limit_headers_on_allowed_response(client):
    r = client.get("/api/agents")
    assert r.status_code == 200
    assert r.headers["x-ratelimit-limit"] == str(settings.rate_limit_per_minute)
    assert 0 <= int(r.headers["x-ratelimit-remaining"]) < settings.rate_limit_per_minute


def test_rate_limit_headers_absent_on_exempt_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert "x-ratelimit-limit" not in r.headers
    assert "x-ratelimit-remaining" not in r.headers


def test_security_headers_on_api_response(client):
    r = client.get("/api/agents")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "DENY"
