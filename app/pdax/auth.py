"""
PDAX authentication manager.

Logs in with the configured account, answers a SOFTWARE_TOKEN_MFA challenge
automatically when `PDAX_OTP_SECRET` is set, and caches the access/id tokens
(10-minute life). When they expire it refreshes via the 30-day refresh token,
falling back to a fresh login if the refresh fails. An asyncio lock keeps
concurrent callers from stampeding the auth endpoints, and a login circuit
breaker fails fast after repeated failures so the real account is never
hammered into an AccountLocked state.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from ..config import settings
from .errors import PdaxError
from .models.auth import TokenSet
from .totp import totp_now

# Relative paths (no leading slash) so they join onto the trailing-slash base.
_LOGIN = "pdax-institution/v1/login"
_OTP = "pdax-institution/v1/login/otp"
_REFRESH = "pdax-institution/v1/refresh-token"

# Refresh this many seconds before the 10-minute access token actually expires.
_EXPIRY_SKEW = 30

# Login circuit breaker: after this many consecutive login failures, fail fast
# with the cached error until the cooldown elapses. This runs against a REAL
# institutional account — hammering a failing login (e.g. from repeated
# probes) risks a PDAX AccountLocked, so back off instead of retrying.
_LOGIN_FAILURE_THRESHOLD = 3
_LOGIN_COOLDOWN_SECONDS = 60.0


class PdaxAuth:
    def __init__(self) -> None:
        self._tokens: TokenSet | None = None
        self._access_expiry: float = 0.0
        self._lock = asyncio.Lock()
        self._login_failures = 0
        self._last_login_error: PdaxError | None = None
        self._breaker_open_until: float = 0.0

    async def access_headers(self, http: httpx.AsyncClient) -> dict[str, str]:
        """Return valid {access_token, id_token} headers, (re)authenticating
        as needed."""
        async with self._lock:
            if self._tokens and time.time() < self._access_expiry:
                return self._headers()
            if self._tokens:
                try:
                    await self._refresh(http)
                    return self._headers()
                except PdaxError:
                    self._tokens = None  # fall through to a clean login
            if (
                self._login_failures >= _LOGIN_FAILURE_THRESHOLD
                and time.time() < self._breaker_open_until
                and self._last_login_error is not None
            ):
                # Breaker open — replay the cached failure without dialing
                # PDAX (a fresh copy, so tracebacks don't accumulate).
                e = self._last_login_error
                raise PdaxError(
                    e.message,
                    code=e.code,
                    name=e.name,
                    http_status=e.http_status,
                    request_id=e.request_id,
                    raw=e.raw,
                )
            try:
                await self._login(http)
            except PdaxError as e:
                self._login_failures += 1
                self._last_login_error = e
                self._breaker_open_until = time.time() + _LOGIN_COOLDOWN_SECONDS
                raise
            self._login_failures = 0
            self._last_login_error = None
            return self._headers()

    def _headers(self) -> dict[str, str]:
        assert self._tokens is not None
        return {
            "access_token": self._tokens.access_token,
            "id_token": self._tokens.id_token,
        }

    def _store(self, tokens: TokenSet) -> None:
        self._tokens = tokens
        self._access_expiry = time.time() + max(0, tokens.expiry - _EXPIRY_SKEW)

    async def _login(self, http: httpx.AsyncClient) -> None:
        if not settings.pdax_username or not settings.pdax_password:
            raise PdaxError(
                "PDAX credentials not configured (set PDAX_USERNAME / PDAX_PASSWORD)",
                code="PAP0401",
            )
        body = {"username": settings.pdax_username, "password": settings.pdax_password}
        data = await _post(http, _LOGIN, body)
        if data.get("challenge_name"):  # MFA challenge — answer with a TOTP code
            await self._answer_mfa(http, data["session"])
            return
        self._store(TokenSet(**data))

    async def _answer_mfa(self, http: httpx.AsyncClient, session: str) -> None:
        if not settings.pdax_otp_secret:
            raise PdaxError(
                "PDAX account requires MFA but PDAX_OTP_SECRET is not set",
                code="InvalidMfaCode",
            )
        otp = totp_now(settings.pdax_otp_secret, timestamp=int(time.time()))
        body = {"session": session, "username": settings.pdax_username, "otp": otp}
        data = await _post(http, _OTP, body)
        self._store(TokenSet(**data))

    async def _refresh(self, http: httpx.AsyncClient) -> None:
        assert self._tokens is not None
        body = {
            "username": settings.pdax_username,
            "refreshToken": self._tokens.refresh_token,
        }
        data = await _put(http, _REFRESH, body)
        self._store(TokenSet(**data))


async def _post(http: httpx.AsyncClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
    return await _send(http, "POST", path, body)


async def _put(http: httpx.AsyncClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
    return await _send(http, "PUT", path, body)


async def _send(http: httpx.AsyncClient, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        resp = await http.request(method, path, json=body, headers={"Content-Type": "application/json"})
    except httpx.HTTPError as e:  # network/transport failure
        raise PdaxError(f"PDAX auth transport error: {e}") from e
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400 or data.get("code") in {
        "InvalidCredentials",
        "InvalidMfaCode",
        "NotAuthorizedException",
        "BadRequestException",
        "AccountLocked",
        "ExpiredTemporaryPassword",
    }:
        raise PdaxError(
            data.get("message", "PDAX authentication failed"),
            code=data.get("code"),
            http_status=resp.status_code,
            raw=data,
        )
    return data
