"""PdaxAuth login circuit breaker: after 3 consecutive login failures the
cached error is replayed without dialing PDAX until a 60s cooldown elapses;
a success resets the counter."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.pdax import auth as auth_mod
from app.pdax.auth import PdaxAuth
from app.pdax.errors import PdaxError
from app.pdax.models.auth import TokenSet


def _fake_clock(monkeypatch, start: float = 1_000.0) -> list[float]:
    now = [start]
    monkeypatch.setattr(auth_mod, "time", SimpleNamespace(time=lambda: now[0]))
    return now


def _failing_login(calls: dict) -> object:
    async def login(http) -> None:
        calls["n"] += 1
        raise PdaxError("bad credentials", code="InvalidCredentials", http_status=401)

    return login


def _token_set() -> TokenSet:
    return TokenSet(
        email="a@b.c",
        username="uuid",
        access_token="at",
        id_token="it",
        refresh_token="rt",
        expiry=600,
    )


def test_breaker_opens_after_three_failures(monkeypatch):
    _fake_clock(monkeypatch)
    auth = PdaxAuth()
    calls = {"n": 0}
    monkeypatch.setattr(auth, "_login", _failing_login(calls))

    async def run() -> None:
        for _ in range(3):
            with pytest.raises(PdaxError):
                await auth.access_headers(None)
        assert calls["n"] == 3
        # Breaker now open: the cached error is replayed, no login attempted.
        with pytest.raises(PdaxError) as exc:
            await auth.access_headers(None)
        assert calls["n"] == 3
        assert exc.value.code == "InvalidCredentials"
        assert exc.value.http_status == 401

    asyncio.run(run())


def test_breaker_allows_retry_after_cooldown(monkeypatch):
    now = _fake_clock(monkeypatch)
    auth = PdaxAuth()
    calls = {"n": 0}
    monkeypatch.setattr(auth, "_login", _failing_login(calls))

    async def run() -> None:
        for _ in range(4):
            with pytest.raises(PdaxError):
                await auth.access_headers(None)
        assert calls["n"] == 3  # 4th call was served by the breaker
        now[0] += 61.0  # cooldown elapses → one real attempt goes through
        with pytest.raises(PdaxError):
            await auth.access_headers(None)
        assert calls["n"] == 4
        # ...and the breaker re-arms immediately at/above the threshold.
        with pytest.raises(PdaxError):
            await auth.access_headers(None)
        assert calls["n"] == 4

    asyncio.run(run())


def test_breaker_resets_on_success(monkeypatch):
    now = _fake_clock(monkeypatch)
    auth = PdaxAuth()
    calls = {"n": 0}
    monkeypatch.setattr(auth, "_login", _failing_login(calls))

    async def run() -> None:
        for _ in range(2):
            with pytest.raises(PdaxError):
                await auth.access_headers(None)

        async def ok_login(http) -> None:
            calls["n"] += 1
            auth._store(_token_set())

        monkeypatch.setattr(auth, "_login", ok_login)
        headers = await auth.access_headers(None)
        assert headers == {"access_token": "at", "id_token": "it"}
        assert auth._login_failures == 0
        assert auth._last_login_error is None

        # A later single failure does not trip the breaker (counter was reset).
        auth._tokens = None
        now[0] += 1.0
        monkeypatch.setattr(auth, "_login", _failing_login(calls))
        with pytest.raises(PdaxError):
            await auth.access_headers(None)
        with pytest.raises(PdaxError):
            await auth.access_headers(None)
        assert auth._login_failures == 2  # both attempts really ran

    asyncio.run(run())
