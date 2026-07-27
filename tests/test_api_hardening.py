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


_CONTRACT_ID_FIELDS = (
    "stellar_agent_registry",
    "stellar_payment_escrow",
    "stellar_attestation_registry",
    "stellar_asset_sac",
    "stellar_reputation_ledger",
)


def _configure_stellar(monkeypatch) -> None:
    for field in _CONTRACT_ID_FIELDS:
        monkeypatch.setattr(settings, field, "C" + "A" * 55)


def test_readiness_ready_without_signing_key(client, monkeypatch):
    """Read-only deployments are legitimate: an absent signer is reported
    but never fails readiness (config.py doctrine)."""
    _configure_stellar(monkeypatch)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "pdax_username", "")
    monkeypatch.setattr(settings, "pdax_password", "")
    r = client.get("/readiness")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ready",
        "llm": "ok",
        "stellar": "configured",
        "signer": "absent",
        "pdax": "unconfigured",
    }


def test_readiness_503_when_llm_key_missing(client, monkeypatch):
    _configure_stellar(monkeypatch)
    monkeypatch.setattr(settings, "openai_api_key", "")
    r = client.get("/readiness")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert body["llm"] == "missing_key"


def test_readiness_503_when_stellar_incomplete(client, monkeypatch):
    _configure_stellar(monkeypatch)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "stellar_agent_registry", "")
    r = client.get("/readiness")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert body["stellar"] == "incomplete"


def test_readiness_reports_configured_signer_and_pdax(client, monkeypatch):
    _configure_stellar(monkeypatch)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "stellar_signing_key", "S" + "A" * 55)
    monkeypatch.setattr(settings, "pdax_username", "ops@example.com")
    monkeypatch.setattr(settings, "pdax_password", "pw")
    body = client.get("/readiness").json()
    assert body["signer"] == "configured"
    assert body["pdax"] == "configured"


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


def test_cors_allows_project_preview_origins(client):
    for origin in (
        "https://orizon-agents-fe-stellar.vercel.app",
        "https://orizon-agents-fe-stellar-git-update-2-team.vercel.app",
    ):
        r = client.options(
            "/api/agents",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == origin


def test_cors_rejects_foreign_vercel_origins(client):
    for origin in (
        "https://evil.vercel.app",
        "https://orizon-agents-fe-stellar.vercel.app.evil.com",
        "http://orizon-agents-fe-stellar.vercel.app",
    ):
        r = client.options(
            "/api/agents",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
        assert "access-control-allow-origin" not in r.headers, origin


def test_security_headers_on_api_response(client):
    r = client.get("/api/agents")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "DENY"


def test_500_handler_allows_preview_origin():
    from app.main import app

    if not any(getattr(r, "path", None) == "/boom-cors-test" for r in app.routes):

        @app.get("/boom-cors-test", include_in_schema=False)
        async def boom() -> None:
            raise RuntimeError("boom")

    preview = "https://orizon-agents-fe-stellar-git-update-2-team.vercel.app"
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom-cors-test", headers={"Origin": preview})
        assert r.status_code == 500
        # The hand-rolled CORS in the 500 handler must apply the same regex
        # as the middleware, or preview deployments can't read the envelope.
        assert r.headers["access-control-allow-origin"] == preview
        foreign = c.get("/boom-cors-test", headers={"Origin": "https://evil.vercel.app"})
        assert foreign.status_code == 500
        assert "access-control-allow-origin" not in foreign.headers


def test_security_headers_on_429():
    from app.main import SecurityHeadersMiddleware

    async def ok(request):
        return PlainTextResponse("ok")

    # Same composition the app registers: the header middleware wrapping the
    # limiter, so its 429 short-circuits pick up the hardening headers.
    inner = Starlette(routes=[Route("/hit", ok)])
    limited = TestClient(SecurityHeadersMiddleware(RateLimitMiddleware(inner, limit=1, window_seconds=60)))

    assert limited.get("/hit").status_code == 200
    blocked = limited.get("/hit")
    assert blocked.status_code == 429
    assert blocked.headers["x-content-type-options"] == "nosniff"
    assert blocked.headers["referrer-policy"] == "no-referrer"
    assert blocked.headers["x-frame-options"] == "DENY"


def test_app_orders_header_middleware_outside_limiter():
    from app.main import app

    names = [m.cls.__name__ for m in app.user_middleware]  # outermost first
    assert names.index("SecurityHeadersMiddleware") < names.index("RateLimitMiddleware")
    assert names.index("RateLimitMiddleware") < names.index("BodyLimitMiddleware")
    # Request-id context is outermost, so 413/429 short-circuits carry it.
    assert names.index("RequestContextMiddleware") == 0
