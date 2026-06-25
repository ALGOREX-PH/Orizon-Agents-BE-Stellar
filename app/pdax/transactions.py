"""
PDAX transaction-tracking endpoints — fiat and crypto histories.

Both return enveloped lists and paginate via page/pageSize. Fiat filters by
mode (CashIn/CashOut) + identifier; crypto filters by identifier, txn_hash,
or type.
"""
from __future__ import annotations

from .client import PdaxClient
from .models.transactions import CryptoTransaction, FiatTransaction


async def fiat_transactions(
    client: PdaxClient,
    *,
    mode: str | None = None,
    identifier: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> list[FiatTransaction]:
    data = await client.request(
        "GET",
        "pdax-institution/v1/fiat/transactions",
        params={
            "mode": mode,
            "identifier": identifier,
            "page": page,
            "pageSize": page_size,
        },
    )
    return [FiatTransaction(**t) for t in data.get("data", [])]


async def crypto_transactions(
    client: PdaxClient,
    *,
    identifier: str | None = None,
    txn_hash: str | None = None,
    type: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> list[CryptoTransaction]:
    data = await client.request(
        "GET",
        "pdax-institution/v1/crypto/transactions",
        params={
            "identifier": identifier,
            "txn_hash": txn_hash,
            "type": type,
            "page": page,
            "pageSize": page_size,
        },
    )
    return [CryptoTransaction(**t) for t in data.get("data", [])]
