"""
PDAX webhook support — endpoint registration and inbound-event helpers.

`register_webhook` subscribes a URL for "crypto" or "fiat" events. PDAX does
not publish a signing scheme, so `verify_signature` is a defensive HMAC-SHA256
check that runs only when `PDAX_WEBHOOK_SECRET` is configured (otherwise it
accepts, leaving IP allow-listing as the trust boundary).
"""
from __future__ import annotations

import hashlib
import hmac

from ..config import settings
from .client import PdaxClient
from .models.webhooks import (
    CryptoEvent,
    FiatEvent,
    WebhookRegisterRequest,
    WebhookRegistration,
)


async def register_webhook(
    client: PdaxClient, req: WebhookRegisterRequest
) -> WebhookRegistration:
    data = await client.request(
        "POST", "pdax-institution/v1/config/webhook", json=req.model_dump()
    )
    return WebhookRegistration(**data["data"])


def verify_signature(raw_body: bytes, signature: str | None) -> bool:
    """Constant-time HMAC-SHA256 check. Returns True when no secret is set."""
    secret = settings.pdax_webhook_secret
    if not secret:
        return True
    if not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_event(payload: dict) -> CryptoEvent | FiatEvent:
    """Coerce an inbound webhook body into the right event model."""
    asset_type = str(payload.get("asset_type", "")).lower()
    if asset_type == "fiat":
        return FiatEvent(**payload)
    return CryptoEvent(**payload)


# Processed-event keys, to make webhook delivery idempotent (PDAX may retry).
_seen_events: set[str] = set()


def event_key(payload: dict) -> str:
    """Stable key identifying a delivery, so retries don't double-process."""
    fields = ("identifier", "request_id", "transaction_hash", "reference_number", "status")
    return "|".join(str(payload.get(f, "")) for f in fields)


def claim_event(key: str) -> bool:
    """Record an event key. Returns False if it was already seen (duplicate)."""
    if key in _seen_events:
        return False
    _seen_events.add(key)
    return True
