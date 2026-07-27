"""PDAX auth guard: money-moving routes need the API key, probes stay public,
and x402 agent ids cannot smuggle CR/LF into response headers."""

from __future__ import annotations

WITHDRAW_BODY = {
    "identifier": "test-wd-1",
    "amount": "100",
    "method": "PAY-TO-ACCOUNT-NON-REAL-TIME",
    "fee_type": "Sender",
    "sender_first_name": "Ada",
    "sender_last_name": "Lovelace",
    "sender_country_origin": "Philippines",
    "source_of_funds": "Compensation",
    "beneficiary_first_name": "Ada",
    "beneficiary_last_name": "Lovelace",
    "beneficiary_bank_code": "TESTBANK",
    "beneficiary_account_name": "Ada Lovelace",
    "beneficiary_account_number": "1234567890",
    "purpose": "Purchase of Goods",
    "relationship_of_sender_to_beneficiary": "Myself",
}


def _fake_result():
    from app.pdax.models.withdrawals import FiatWithdrawResult

    return FiatWithdrawResult(
        identifier="test-wd-1",
        amount=100.0,
        method="PAY-TO-ACCOUNT-NON-REAL-TIME",
        status="PENDING",
    )


def test_fiat_withdraw_rejected_without_api_key(client, hermetic_settings):
    hermetic_settings.api_key = "secret-key"
    r = client.post("/api/pdax/fiat/withdraw", json=WITHDRAW_BODY)
    assert r.status_code == 401


def test_fiat_withdraw_passes_guard_with_api_key(client, hermetic_settings, monkeypatch):
    hermetic_settings.api_key = "secret-key"

    async def fake_fiat_withdraw(client_, req):
        return _fake_result()

    monkeypatch.setattr("app.routers.pdax.get_pdax_client", lambda: object())
    monkeypatch.setattr("app.pdax.withdrawals.fiat_withdraw", fake_fiat_withdraw)

    r = client.post(
        "/api/pdax/fiat/withdraw",
        json=WITHDRAW_BODY,
        headers={"X-API-Key": "secret-key"},
    )
    # Past the guard — the mocked PDAX call answers instead of the network.
    assert r.status_code == 200
    assert r.json()["status"] == "PENDING"


def test_pdax_health_needs_no_api_key(client, hermetic_settings, monkeypatch):
    hermetic_settings.api_key = "secret-key"
    # Blank the PDAX credentials — the public probe reads settings only and
    # must report configured=False without dialing anything.
    from app.config import settings

    monkeypatch.setattr(settings, "pdax_username", "")
    monkeypatch.setattr(settings, "pdax_password", "")

    r = client.get("/api/pdax/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["configured"] is False


def test_x402_rejects_crlf_agent_id(client):
    r = client.post(
        "/api/payments/x402",
        json={"agent_id": "a\r\nX-Injected: yes", "amount_usdc": 1.0},
    )
    assert r.status_code == 422
