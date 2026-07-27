"""PDAX surface: webhook fail-closed, ramp input validation."""
from __future__ import annotations

VALID_G = "G" + "A" * 55

ONRAMP_BODY = {
    "php_amount": "500",
    "stellar_address": VALID_G,
    "method": "instapay_upay_cashin",
    "identifier": "test-1",
    "sender_first_name": "Ada",
    "sender_last_name": "Lovelace",
    "beneficiary_first_name": "Ada",
    "beneficiary_last_name": "Lovelace",
}


def test_webhook_rejected_when_unsigned(client, monkeypatch):
    from app.pdax import config as pdax_config

    monkeypatch.setattr(pdax_config, "allow_unsigned_webhooks", lambda: False)
    r = client.post("/api/pdax/webhooks/receive", json={"type": "x", "id": "1"})
    assert r.status_code == 401


def test_ramp_estimate_rejects_garbage_amount(client):
    r = client.post("/api/pdax/ramp/estimate?direction=onramp&amount=garbage")
    assert r.status_code == 422


def test_ramp_estimate_rejects_negative_amount(client):
    r = client.post("/api/pdax/ramp/estimate?direction=onramp&amount=-100")
    assert r.status_code == 422


def test_ramp_estimate_rejects_bad_direction(client):
    # `direction` is a Literal — FastAPI rejects bad values with its own
    # 422 validation envelope before the handler runs.
    r = client.post("/api/pdax/ramp/estimate?direction=sideways&amount=100")
    assert r.status_code == 422
    assert any(e["loc"][-1] == "direction" for e in r.json()["detail"])


def test_onramp_rejects_bad_stellar_address(client):
    r = client.post(
        "/api/pdax/ramp/onramp",
        json={**ONRAMP_BODY, "stellar_address": "not-stellar"},
    )
    assert r.status_code == 422


def test_onramp_rejects_nonnumeric_amount(client):
    r = client.post(
        "/api/pdax/ramp/onramp",
        json={**ONRAMP_BODY, "php_amount": "lots"},
    )
    assert r.status_code == 422


def test_funding_quote_rejects_garbage(client):
    r = client.post("/api/pdax/ramp/funding-quote?usdc=NaN")
    assert r.status_code == 422
