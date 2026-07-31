"""Malformed upstream input must become a typed PdaxError, never a 500.

PdaxError is what `with_retries` retries on and what every route translates
(`_fail` → 502 upstream_unavailable). Anything else escapes both, so a
gateway HTML page from PDAX would read to the client as an Orizon bug.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.pdax import auth as auth_mod
from app.pdax.auth import PdaxAuth, _send
from app.pdax.errors import PdaxError, orizon_code
from app.pdax.resilience import is_retryable
from app.pdax.totp import totp_now


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://pdax.test/")


def _send_once(handler) -> dict:
    async def run() -> dict:
        async with _client(handler) as http:
            return await _send(http, "POST", "login", {"username": "u"})

    return asyncio.run(run())


def test_html_gateway_page_becomes_typed_upstream_error():
    """A Cloudflare/WAF error page is not JSON — resp.json() raises ValueError
    inside _send, which used to escape as 500 internal_error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html><body>502 Bad Gateway</body></html>")

    with pytest.raises(PdaxError) as exc:
        _send_once(handler)
    e = exc.value
    assert e.http_status == 502
    assert "502 Bad Gateway" in e.message
    # 502 is transient, so the transport may legitimately retry it...
    assert is_retryable(e) is True
    # ...and the client sees an upstream outage, not an app fault.
    assert orizon_code(e.code) == "pdax_error"


def test_json_array_error_body_becomes_typed_upstream_error():
    """Valid JSON, wrong shape: a list has no .get, which used to raise
    AttributeError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=[{"code": "InvalidCredentials"}])

    with pytest.raises(PdaxError) as exc:
        _send_once(handler)
    assert exc.value.http_status == 400
    assert "PDAX authentication failed" in exc.value.message


def test_json_array_success_body_becomes_typed_upstream_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "a", "token", "set"])

    with pytest.raises(PdaxError) as exc:
        _send_once(handler)
    assert exc.value.code == "bad_upstream_shape"


def test_non_json_success_body_becomes_typed_upstream_error(monkeypatch):
    """A 200 carrying an HTML maintenance page: _send salvages it as
    {"message": ...} (like client._parse), and the token-set guard rejects it
    as a typed upstream error instead of a ValidationError 500."""
    monkeypatch.setattr(auth_mod.settings, "pdax_username", "u")
    monkeypatch.setattr(auth_mod.settings, "pdax_password", "p")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    async def run() -> None:
        async with _client(handler) as http:
            await PdaxAuth().access_headers(http)

    with pytest.raises(PdaxError) as exc:
        asyncio.run(run())
    assert exc.value.code == "bad_upstream_shape"


def test_typed_error_body_still_surfaces_its_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": "InvalidCredentials", "message": "Incorrect username or password."})

    with pytest.raises(PdaxError) as exc:
        _send_once(handler)
    assert exc.value.code == "InvalidCredentials"
    assert orizon_code(exc.value.code) == "invalid_credentials"


def test_ok_body_is_returned_unchanged():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"challenge_name": "SOFTWARE_TOKEN_MFA", "session": "s1"})

    assert _send_once(handler)["session"] == "s1"


def test_token_shaped_2xx_missing_fields_is_typed(monkeypatch):
    """A 200 that is a JSON object but not a token set must not escape as a
    pydantic ValidationError 500."""
    monkeypatch.setattr(auth_mod.settings, "pdax_username", "u")
    monkeypatch.setattr(auth_mod.settings, "pdax_password", "p")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    async def run() -> None:
        async with _client(handler) as http:
            await PdaxAuth().access_headers(http)

    with pytest.raises(PdaxError) as exc:
        asyncio.run(run())
    assert exc.value.code == "bad_upstream_shape"


def test_mfa_challenge_without_session_is_typed(monkeypatch):
    monkeypatch.setattr(auth_mod.settings, "pdax_username", "u")
    monkeypatch.setattr(auth_mod.settings, "pdax_password", "p")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"challenge_name": "SOFTWARE_TOKEN_MFA"})

    async def run() -> None:
        async with _client(handler) as http:
            await PdaxAuth().access_headers(http)

    with pytest.raises(PdaxError) as exc:
        asyncio.run(run())
    assert exc.value.code == "InvalidMfaCode"


def test_malformed_otp_secret_is_typed_not_binascii_error():
    """A mistyped PDAX_OTP_SECRET used to raise binascii.Error on the first
    MFA login — an unhandled 500 rather than a PDAX auth failure."""
    with pytest.raises(PdaxError) as exc:
        totp_now("not-valid-base32!", timestamp=59)
    assert exc.value.code == "InvalidMfaCode"
    assert orizon_code(exc.value.code) == "invalid_mfa_code"


def test_empty_otp_secret_is_typed():
    with pytest.raises(PdaxError):
        totp_now("A", timestamp=59)
