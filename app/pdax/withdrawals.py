"""
PDAX withdrawal endpoints — fiat withdraw, user-info upload, and crypto out.

`fiat_withdraw` and `user_info_upload` return an enveloped result whose
`status` may be PENDING/FAILED with per-channel attempts in `retry_methods`
(a FAILED business result is returned, not raised). `crypto_out` returns a
flat payload.
"""
from __future__ import annotations

from .client import PdaxClient
from .models.withdrawals import (
    CryptoOutRequest,
    CryptoOutResult,
    FiatWithdrawRequest,
    FiatWithdrawResult,
)


async def fiat_withdraw(client: PdaxClient, req: FiatWithdrawRequest) -> FiatWithdrawResult:
    data = await client.request(
        "POST", "pdax-institution/v1/fiat/withdraw", json=req.model_dump(exclude_none=True)
    )
    return FiatWithdrawResult(**(data.get("data", data)))


async def user_info_upload(client: PdaxClient, req: FiatWithdrawRequest) -> FiatWithdrawResult:
    data = await client.request(
        "POST",
        "pdax-institution/v1/fiat/user-info-upload",
        json=req.model_dump(exclude_none=True),
    )
    return FiatWithdrawResult(**(data.get("data", data)))


async def crypto_out(client: PdaxClient, req: CryptoOutRequest) -> CryptoOutResult:
    data = await client.request(
        "POST", "pdax-institution/v1/crypto/withdraw", json=req.model_dump(exclude_none=True)
    )
    # Crypto out returns a flat payload (no envelope).
    return CryptoOutResult(**(data.get("data", data)))
