"""
PDAX funding endpoints — crypto deposit address and fiat deposit (cash-in).

`crypto_deposit_address` returns the wallet to send a token to (enveloped).
`fiat_deposit` returns a flat payload (no `data` wrapper) carrying the
`payment_checkout_url` to complete the cash-in.
"""
from __future__ import annotations

from . import validation
from .client import PdaxClient
from .models.funding import (
    CryptoDepositAddress,
    FiatDepositRequest,
    FiatDepositResult,
)


async def crypto_deposit_address(client: PdaxClient, currency: str) -> CryptoDepositAddress:
    data = await client.request(
        "GET", "pdax-institution/v1/crypto/deposit", params={"currency": currency}
    )
    return CryptoDepositAddress(**data["data"])


async def fiat_deposit(client: PdaxClient, req: FiatDepositRequest) -> FiatDepositResult:
    validation.validate_fiat_deposit(req)
    data = await client.request(
        "POST", "pdax-institution/v1/fiat/deposit", json=req.model_dump(exclude_none=True)
    )
    # Fiat deposit returns a flat payload (no envelope).
    return FiatDepositResult(**(data.get("data", data)))
