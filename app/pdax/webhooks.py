"""
PDAX webhook support — endpoint registration and inbound-event helpers.

`register_webhook` subscribes a URL for "crypto" or "fiat" events. PDAX does
not publish a signing scheme, so `verify_signature` is a defensive HMAC-SHA256
check against `PDAX_WEBHOOK_SECRET`. With no secret configured it fails
closed; local dev/smoke can opt out via PDAX_ALLOW_UNSIGNED_WEBHOOKS=true
(leaving IP allow-listing as the trust boundary).
"""
from __future__ import annotations

import hashlib
import hmac
from collections import OrderedDict

from ..config import settings
from .client import PdaxClient
from .config import allow_unsigned_webhooks
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
    """Constant-time HMAC-SHA256 check. Fails closed when no secret is set
    unless PDAX_ALLOW_UNSIGNED_WEBHOOKS explicitly opts local dev out."""
    secret = settings.pdax_webhook_secret
    if not secret:
        return allow_unsigned_webhooks()
    if not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    # Compare utf-8 bytes, not str: compare_digest raises TypeError on
    # non-ASCII str input (Starlette decodes headers latin-1), which would
    # turn a bad signature into a 500 instead of a 401.
    return hmac.compare_digest(expected.encode(), signature.encode("utf-8", "ignore"))


def parse_event(payload: dict) -> CryptoEvent | FiatEvent:
    """Coerce an inbound webhook body into the right event model."""
    asset_type = str(payload.get("asset_type", "")).lower()
    if asset_type == "fiat":
        return FiatEvent(**payload)
    return CryptoEvent(**payload)


# Processed-event keys, to make webhook delivery idempotent (PDAX may retry).
# Bounded LRU (insertion-ordered dict) so a long-lived process can't grow it
# forever; retries arrive within minutes, so the last 10k keys is ample.
_SEEN_EVENTS_MAX = 10_000
_seen_events: OrderedDict[str, None] = OrderedDict()


def event_key(payload: dict) -> str:
    """Stable key identifying a delivery, so retries don't double-process."""
    fields = ("identifier", "request_id", "transaction_hash", "reference_number", "status")
    return "|".join(str(payload.get(f, "")) for f in fields)


def claim_event(key: str) -> bool:
    """Record an event key. Returns False if it was already seen (duplicate)."""
    if key in _seen_events:
        _seen_events.move_to_end(key)
        return False
    _seen_events[key] = None
    while len(_seen_events) > _SEEN_EVENTS_MAX:
        _seen_events.popitem(last=False)
    return True
