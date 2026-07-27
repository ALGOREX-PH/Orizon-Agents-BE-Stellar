"""PDAX webhook receiver: signature verification edge cases."""
from __future__ import annotations

import hashlib
import hmac

from app.config import settings
from app.pdax import webhooks as pw


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
