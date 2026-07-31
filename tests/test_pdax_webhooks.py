"""PDAX webhook receiver: signature verification edge cases, the HMAC accept
path, and claim_event idempotency."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid

import pytest
from pydantic import ValidationError

from app.config import settings
from app.pdax import webhooks as pw
from app.pdax.errors import PdaxError


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
    monkeypatch.setattr(pdax_config, "settings", SimpleNamespace(pdax_allow_unsigned_webhooks=False))
    assert pdax_config.allow_unsigned_webhooks() is False

    monkeypatch.setattr(pdax_config, "settings", SimpleNamespace(pdax_allow_unsigned_webhooks=True))
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
    assert body["matched"] is False


def test_unmatched_settlement_is_200_but_flagged_and_logged(client, monkeypatch, caplog):
    """PDAX retries non-2xx, and ramp state is process-local: an event that
    matches nothing now will match nothing on redelivery either. So the
    delivery is accepted (no retry storm) but reported as matched=false and
    logged at warning, which is what an operator acts on."""
    monkeypatch.setattr(settings, "pdax_webhook_secret", "s3cret")
    monkeypatch.setattr("app.routers.pdax.get_pdax_client", lambda: object())
    payload = _crypto_payload()
    with caplog.at_level(logging.WARNING, logger="app.pdax.ramp"):
        r = _post_signed(client, payload)
    assert r.status_code == 200
    assert r.json()["matched"] is False
    warnings = [rec.getMessage() for rec in caplog.records if rec.levelno == logging.WARNING]
    assert any("unmatched settlement event" in m and payload["identifier"] in m for m in warnings), warnings


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


@pytest.mark.parametrize("body", [[{"identifier": "x"}], "just-a-string", 42, None])
def test_signed_non_object_body_is_400_not_500(client, monkeypatch, body):
    """A correctly signed body that isn't a JSON object still reaches
    event_key/parse_event, which index it by key. Malformed input is the
    caller's fault (400), not ours (500)."""
    monkeypatch.setattr(settings, "pdax_webhook_secret", "s3cret")
    raw = json.dumps(body).encode()
    r = client.post(
        "/api/pdax/webhooks/receive",
        content=raw,
        headers={
            "content-type": "application/json",
            "x-pdax-signature": _sign("s3cret", raw),
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid webhook payload"


def test_non_object_body_takes_no_idempotency_claim(client, monkeypatch):
    """The 400 must happen before claim_event, so nothing is left claimed for
    a delivery that never took effect."""
    monkeypatch.setattr(settings, "pdax_webhook_secret", "s3cret")
    raw = json.dumps([{"identifier": "arr-1"}]).encode()
    client.post(
        "/api/pdax/webhooks/receive",
        content=raw,
        headers={"content-type": "application/json", "x-pdax-signature": _sign("s3cret", raw)},
    )
    assert pw._seen_events == {}


def test_failed_handling_releases_claim_so_retry_succeeds(client, monkeypatch):
    """A delivery whose side effect failed must not poison the retry: the
    claim is released, so PDAX's redelivery is processed instead of being
    answered with {"duplicate": true} and dropped forever."""
    monkeypatch.setattr(settings, "pdax_webhook_secret", "s3cret")
    monkeypatch.setattr("app.routers.pdax.get_pdax_client", lambda: object())
    calls = {"n": 0}

    async def flaky_handle(client_, event):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PdaxError("upstream exploded", http_status=500)
        return None

    monkeypatch.setattr("app.pdax.ramp.handle_event", flaky_handle)
    payload = _crypto_payload()
    first = _post_signed(client, payload)
    assert first.status_code == 502
    second = _post_signed(client, payload)
    assert second.status_code == 200
    assert "duplicate" not in second.json()
    assert calls["n"] == 2


def test_successful_handling_keeps_claim(client, monkeypatch):
    """After a delivery fully takes effect, the retry is still deduped."""
    monkeypatch.setattr(settings, "pdax_webhook_secret", "s3cret")
    monkeypatch.setattr("app.routers.pdax.get_pdax_client", lambda: object())
    calls = {"n": 0}

    async def ok_handle(client_, event):
        calls["n"] += 1
        return None

    monkeypatch.setattr("app.pdax.ramp.handle_event", ok_handle)
    payload = _crypto_payload()
    assert _post_signed(client, payload).status_code == 200
    retry = _post_signed(client, payload)
    assert retry.status_code == 200
    assert retry.json() == {"received": True, "duplicate": True}
    assert calls["n"] == 1


def test_parse_error_releases_claim(client, monkeypatch):
    """A payload that fails event validation after claiming must release the
    claim — the parse never took effect, so a (fixed) retry must not be
    treated as a duplicate."""
    monkeypatch.setattr(settings, "pdax_webhook_secret", "s3cret")
    payload = {"asset_type": "crypto", "status": "completed"}  # missing required fields
    with pytest.raises(ValidationError):
        _post_signed(client, payload)
    assert pw.event_key(payload) not in pw._seen_events


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
