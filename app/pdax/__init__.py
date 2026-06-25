"""
PDAX institutions API integration.

A thin, typed async wrapper around the PDAX exchange API (PHP ↔ crypto
on/off-ramp) that mirrors the `app/stellar/` integration style: a transport
client (`PdaxClient`) with an auth-token manager, Pydantic models per domain,
and domain modules (trade / funding / withdrawals / transactions / balances /
webhooks). For Orizon the key asset is USDCXLM — USDC on Stellar.
"""
from __future__ import annotations

from . import (
    balances,
    funding,
    trade,
    transactions,
    webhooks,
    withdrawals,
)
from .client import PdaxClient, get_pdax_client
from .config import base_url, is_production
from .errors import PdaxError

__all__ = [
    "PdaxClient",
    "get_pdax_client",
    "PdaxError",
    "base_url",
    "is_production",
    "trade",
    "funding",
    "withdrawals",
    "transactions",
    "balances",
    "webhooks",
]
