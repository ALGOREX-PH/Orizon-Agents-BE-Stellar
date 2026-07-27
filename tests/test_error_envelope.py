"""The unified error envelope: every error body keeps the legacy "detail"
key and adds an "error" object with code / message / request_id."""
from __future__ import annotations

CHARGE_BODY = {
    "auth_id_hex": "ab" * 16,
    "amount_usdc": 1.0,
    "job_id_hex": "cd" * 16,
}


def test_http_exception_keeps_detail_and_adds_error(client):
    r = client.get("/api/agents/nope", headers={"X-Request-ID": "env-http-1"})
    assert r.status_code == 404
    body = r.json()
    assert body["detail"] == "unknown agent: nope"
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == "unknown agent: nope"
    assert body["error"]["request_id"] == "env-http-1"


def test_snake_case_detail_is_promoted_to_error_code(client, hermetic_settings):
    hermetic_settings.api_key = "secret-key"
    r = client.post(
        "/api/stellar/server/charge",
        json=CHARGE_BODY,
        headers={"X-Request-ID": "env-http-2"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["detail"] == "invalid_api_key"
    assert body["error"]["code"] == "invalid_api_key"
    assert body["error"]["request_id"] == "env-http-2"


def test_unknown_route_gets_generic_code(client):
    r = client.get("/api/definitely-not-here")
    assert r.status_code == 404
    body = r.json()
    assert body["detail"] == "Not Found"
    assert body["error"]["code"] == "not_found"


def test_validation_error_keeps_detail_list_and_adds_error(client):
    r = client.post(
        "/api/orchestrator/execute",
        json={"plan_id": "nope", "payer": "not-an-address"},
        headers={"X-Request-ID": "env-val-1"},
    )
    assert r.status_code == 422
    body = r.json()
    # Legacy shape untouched: the standard FastAPI list of error objects.
    assert isinstance(body["detail"], list)
    assert all("loc" in e and "msg" in e for e in body["detail"])
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["request_id"] == "env-val-1"
