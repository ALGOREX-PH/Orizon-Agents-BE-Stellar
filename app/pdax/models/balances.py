"""
PDAX balance model — GET /v1/balances[?currency=...].

`available` is free for trading/withdrawal; `hold` is locked by open orders or
pending withdrawals; `total` = available + hold.
"""
from __future__ import annotations

from pydantic import BaseModel


class Balance(BaseModel):
    currency: str
    available: str
    hold: str = "0"
    total: str
    asset_type: str  # FIAT | CRYPTO
