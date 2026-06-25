"""
PDAX balances endpoint — GET /v1/balances[?currency=...].

Returns one `Balance` per asset (or just the requested currency).
"""
from __future__ import annotations

from .client import PdaxClient
from .models.balances import Balance


async def get_balances(client: PdaxClient, currency: str | None = None) -> list[Balance]:
    data = await client.request(
        "GET", "pdax-institution/v1/balances", params={"currency": currency}
    )
    return [Balance(**b) for b in data.get("data", [])]
