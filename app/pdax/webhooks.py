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

from pydantic import ValidationError

from ..config import settings
from .client import PdaxClient
from .config import allow_unsigned_webhooks
from .errors import PdaxError
from .models.webhooks import (
    CryptoEvent,
    FiatEvent,
    WebhookRegisterRequest,
    WebhookRegistration,
)
from .trade import _unwrap


async def register_webhook(client: PdaxClient, req: WebhookRegisterRequest) -> WebhookRegistration:
    data = await client.request("POST", "pdax-institution/v1/config/webhook", json=req.model_dump())
    return _unwrap(data, WebhookRegistration)


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
    """Coerce an inbound webhook body into the right event model.

    A signed body that fits neither event model is permanently bad: it fails
    identically on every redelivery. Fold the ValidationError into a PdaxError
    carrying http_status=400 so the receiver answers a terminal 4xx (`_fail`
    passes client-input 4xx through) instead of the 500 that had PDAX retrying
    an unparseable payload forever.
    """
    asset_type = str(payload.get("asset_type", "")).lower()
    try:
        if asset_type == "fiat":
            return FiatEvent(**payload)
        return CryptoEvent(**payload)
    except ValidationError as e:
        raise PdaxError(
            "unparseable PDAX webhook payload",
            code="bad_webhook_payload",
            http_status=400,
        ) from e


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


def release_event(key: str) -> None:
    """Forget a claimed key so PDAX's retry is processed instead of deduped.

    A claim must not outlive a failed side effect: if parsing or handling
    raises after `claim_event`, the event never took effect, and swallowing
    the retry as a duplicate would drop it forever.
    """
    _seen_events.pop(key, None)
