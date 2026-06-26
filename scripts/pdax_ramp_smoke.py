"""
Offline end-to-end check of the PHP <-> USDCXLM ramp orchestration.

Drives both flows through a fake PDAX client (canned, PDAX-shaped responses) so
the sequencing — fiat deposit → buy → withdraw, and deposit address → sell →
fiat withdraw — is verified without live credentials or IP whitelisting.

Usage:
    cd ~/Websites-2026/orizon-agents-FE-Stellar/backend
    python3 scripts/pdax_ramp_smoke.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pdax import ramp
from app.pdax.models.ramp import OffRampRequest, OnRampRequest
from app.pdax.models.webhooks import CryptoEvent, FiatEvent


def _quote(side: str, qid: str | None = None) -> dict:
    q = {
        "quote_currency": "USDC", "base_currency": "PHP", "side": side,
        "base_quantity": 17.18, "price": 58.2, "total_amount": 1000,
    }
    if qid:
        q |= {"quote_id": qid, "expires_at": "2026-01-01T00:00:15Z"}
    return q


class FakeClient:
    """Returns canned PDAX-shaped payloads keyed by request path."""

    async def request(self, method, path, *, params=None, json=None, authenticated=True):
        if "v2/trade/price" in path:
            return {"data": _quote(params["side"])}
        if "v2/trade/quote" in path:
            return {"data": _quote(json["side"], qid="q-" + json["side"])}
        if path.endswith("/v1/trade"):
            return {"data": {"order_id": 111, "status": "successful", **_quote(json["side"])}}
        if "fiat/deposit" in path:
            return {
                "request_id": "req1", "identifier": json["identifier"],
                "reference_number": "ref1", "amount": 1000, "method": json["method"],
                "payment_checkout_url": "https://pay.example/checkout", "fee": 30,
                "status": "PENDING",
            }
        if "crypto/deposit" in path:
            return {"data": {"currency": "USDCXLM", "address": "GDEPOSITADDR", "tag": "123"}}
        if "crypto/withdraw" in path:
            return {
                "identifier": json["identifier"], "transaction_id": 222,
                "transaction_hash": "", "amount": json["amount"], "address": json["address"],
                "tag": None, "total": json["amount"], "fee": "0.01", "currency": "USDCXLM",
                "status": "IN PROGRESS", "created_at": "2026-01-01T00:00:00Z",
            }
        if "fiat/withdraw" in path:
            return {"data": {
                "request_id": "wreq1", "identifier": json["identifier"],
                "amount": 945, "method": json["method"], "status": "PENDING",
                "retry_methods": [],
            }}
        raise AssertionError(f"unexpected path {path}")


async def main() -> None:
    fake = FakeClient()

    # ── on-ramp: PHP → USDCXLM ──
    rec = await ramp.start_onramp(fake, OnRampRequest(
        php_amount="1000", stellar_address="GBUYERWALLET", method="instapay_upay_cashin",
        identifier="onramp-1", sender_first_name="Juan", sender_last_name="Cruz",
        beneficiary_first_name="Juan", beneficiary_last_name="Cruz",
    ))
    assert rec.status == "awaiting_payment", rec.status
    assert rec.checkout_url, "no checkout url"
    print("on-ramp started:", rec.ramp_id, "→", rec.checkout_url)

    advanced = await ramp.handle_event(fake, FiatEvent(
        user_id="u", identifier="onramp-1", amount=1000,
        transaction_type="DEPOSIT", status="COMPLETED",
    ))
    assert advanced and advanced.status == "completed", advanced
    assert advanced.order_id == 111 and advanced.crypto_tx_id == 222
    print("on-ramp settled: order", advanced.order_id, "tx", advanced.crypto_tx_id,
          f"({advanced.usdc_amount} USDCXLM → {advanced.stellar_address})")

    # ── off-ramp: USDCXLM → PHP ──
    rec2 = await ramp.start_offramp(fake, OffRampRequest(
        usdc_amount="17.18", identifier="offramp-1", beneficiary_bank_code="BAUBPPH",
        beneficiary_account_name="Juan Cruz", beneficiary_account_number="00123456789",
        sender_first_name="Juan", sender_last_name="Cruz",
        beneficiary_first_name="Juan", beneficiary_last_name="Cruz",
    ))
    assert rec2.status == "awaiting_payment" and rec2.deposit_address == "GDEPOSITADDR"
    print("off-ramp started:", rec2.ramp_id, "→ deposit", rec2.deposit_address)

    advanced2 = await ramp.handle_event(fake, CryptoEvent(
        user_id="u", transaction_type="DEPOSIT", status="completed",
        amount=17.18, asset="USDCXLM", destination_address="GDEPOSITADDR",
    ))
    assert advanced2 and advanced2.status == "completed", advanced2
    assert advanced2.withdraw_request_id == "wreq1"
    print("off-ramp settled: order", advanced2.order_id,
          f"({advanced2.usdc_amount} USDC → {advanced2.php_amount} PHP)")

    print("PDAX ramp smoke: ALL OK")


if __name__ == "__main__":
    asyncio.run(main())
