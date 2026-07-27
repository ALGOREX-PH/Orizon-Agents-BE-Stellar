"""PDAX webhook receiver: signature verification edge cases, the HMAC accept
path, and claim_event idempotency."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest

from app.config import settings
from app.pdax import webhooks as pw


@pytest.fixture(autouse=True)
def clean_seen_events():
    pw._seen_events.clear()
    yield
    pw._seen_events.clear()


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_non_ascii_signature_rejected_not_500(client, monkeypatch):
    """A non-ASCII signature header must be a clean 401, never a TypeError 500
    (Starlette decodes header values latin-1)."""
    monkeypatch.setattr(settings, "pdax_webhook_secret", "s3cret")
    r = client.post(
        "/api/pdax/webhooks/receive",
        content=b"{}",
        headers={
            b"content-type": b"application/json",
            # bytes, so httpx forwards it raw; Starlette decodes latin-1
            b"x-pdax-signature": "sigÿþ".encode("latin-1"),
        },
    )
    assert r.status_code == 401


def test_verify_signature_non_ascii_returns_false(monkeypatch):
    monkeypatch.setattr(settings, "pdax_webhook_secret", "s3cret")
    assert pw.verify_signature(b"{}", "ÿ" * 8) is False


def test_verify_signature_valid_hmac(monkeypatch):
    monkeypatch.setattr(settings, "pdax_webhook_secret", "s3cret")
    body = b'{"hello": "world"}'
    assert pw.verify_signature(body, _sign("s3cret", body)) is True


def test_verify_signature_wrong_hmac(monkeypatch):
    monkeypatch.setattr(settings, "pdax_webhook_secret", "s3cret")
    body = b'{"hello": "world"}'
    assert pw.verify_signature(body, _sign("other", body)) is False


def test_allow_unsigned_webhooks_reads_settings_not_env(monkeypatch):
    """The escape hatch is driven by the validated Settings field only — a
    raw env var set at call time must no longer bypass it."""
    from types import SimpleNamespace

    from app.pdax import config as pdax_config

    monkeypatch.setenv("PDAX_ALLOW_UNSIGNED_WEBHOOKS", "true")
    monkeypatch.setattr(
        pdax_config, "settings", SimpleNamespace(pdax_allow_unsigned_webhooks=False)
    )
    assert pdax_config.allow_unsigned_webhooks() is False

    monkeypatch.setattr(
        pdax_config, "settings", SimpleNamespace(pdax_allow_unsigned_webhooks=True)
    )
    assert pdax_config.allow_unsigned_webhooks() is True


def test_allow_unsigned_webhooks_defaults_false():
    from app.pdax import config as pdax_config

    assert pdax_config.allow_unsigned_webhooks() is False


def _crypto_payload() -> dict:
    return {
        "identifier": f"wh-{uuid.uuid4().hex[:8]}",
        "user_id": "u1",
        "transaction_type": "DEPOSIT",
        "amount": 5.0,
        "asset": "USDCXLM",
        "asset_type": "crypto",
        "destination_address": "GNOMATCH",
        "status": "completed",
    }


def _post_signed(client, payload: dict):
    body = json.dumps(payload).encode()
    return client.post(
        "/api/pdax/webhooks/receive",
        content=body,
        headers={
            "content-type": "application/json",
            "x-pdax-signature": _sign("s3cret", body),
        },
    )


def test_valid_hmac_accepts_and_parses_event(client, monkeypatch):
    monkeypatch.setattr(settings, "pdax_webhook_secret", "s3cret")
    monkeypatch.setattr("app.routers.pdax.get_pdax_client", lambda: object())
    payload = _crypto_payload()
    r = _post_signed(client, payload)
    assert r.status_code == 200
    body = r.json()
    assert body["received"] is True
    assert body["event"]["asset"] == "USDCXLM"
    assert body["event"]["amount"] == 5.0
    assert body["ramp"] is None  # no waiting ramp matched


def test_duplicate_delivery_is_rejected_idempotently(client, monkeypatch):
    monkeypatch.setattr(settings, "pdax_webhook_secret", "s3cret")
    monkeypatch.setattr("app.routers.pdax.get_pdax_client", lambda: object())
    payload = _crypto_payload()
    first = _post_signed(client, payload)
    assert first.status_code == 200
    assert "duplicate" not in first.json()
    second = _post_signed(client, payload)
    assert second.status_code == 200
    assert second.json() == {"received": True, "duplicate": True}


def test_bad_json_with_valid_signature_is_400(client, monkeypatch):
    monkeypatch.setattr(settings, "pdax_webhook_secret", "s3cret")
    raw = b"not-json"
    r = client.post(
        "/api/pdax/webhooks/receive",
        content=raw,
        headers={
            "content-type": "application/json",
            "x-pdax-signature": _sign("s3cret", raw),
        },
    )
    assert r.status_code == 400


def test_claim_event_second_claim_rejected():
    key = f"k-{uuid.uuid4().hex}"
    assert pw.claim_event(key) is True
    assert pw.claim_event(key) is False


def test_claim_event_bounded():
    for i in range(pw._SEEN_EVENTS_MAX + 50):
        pw.claim_event(f"bulk-{i}")
    assert len(pw._seen_events) == pw._SEEN_EVENTS_MAX
    # Oldest keys were evicted, newest kept.
    assert "bulk-0" not in pw._seen_events
    assert f"bulk-{pw._SEEN_EVENTS_MAX + 49}" in pw._seen_events
