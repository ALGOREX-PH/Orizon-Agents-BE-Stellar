"""Story 1.09 — the agent-id availability check caches its Soroban read.

Repeated blur checks of the same id, and any concurrent burst, collapse to a
single upstream read within the TTL window (AC2). The malformed/reserved
short-circuits never touch the chain at all. Ids are unique per test so the
in-process cache cannot leak an outcome across tests.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import app.stellar.client as sc
from app.routers.stellar import agent_id_available
from app.stellar import cache as rcache


@pytest.fixture(autouse=True)
def _clear_cache() -> Any:
    rcache.clear()
    yield
    rcache.clear()


def test_repeated_available_checks_hit_rpc_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_read(*_a: object, **_k: object) -> dict[str, Any]:
        calls["n"] += 1
        raise RuntimeError("HostError: no such agent")  # unknown id → available

    monkeypatch.setattr(sc, "simulate_read", fake_read)

    async def go() -> list[Any]:
        return [await agent_id_available("cache_free_id") for _ in range(5)]

    results = asyncio.run(go())

    assert all(r.available for r in results)
    assert calls["n"] == 1  # five checks, one Soroban read


def test_repeated_taken_checks_hit_rpc_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_read(*_a: object, **_k: object) -> dict[str, Any]:
        calls["n"] += 1
        return {"id": "cache_taken_id", "owner": "GBI2ABC"}

    monkeypatch.setattr(sc, "simulate_read", fake_read)

    async def go() -> list[Any]:
        return [await agent_id_available("cache_taken_id") for _ in range(4)]

    results = asyncio.run(go())

    assert all((not r.available and r.reason == "id_taken") for r in results)
    assert results[0].owner == "GBI2ABC"  # the taken outcome (incl. owner) is cached
    assert calls["n"] == 1


def test_concurrent_checks_single_flight_to_one_rpc(monkeypatch: pytest.MonkeyPatch) -> None:
    # A burst of simultaneous blur checks of the same id must share one flight
    # (get_or_set's single-flight), not fan out one RPC each.
    calls = {"n": 0}

    def fake_read(*_a: object, **_k: object) -> dict[str, Any]:
        calls["n"] += 1
        return {"id": "cache_hot_id", "owner": "GHOT"}

    monkeypatch.setattr(sc, "simulate_read", fake_read)

    async def go() -> list[Any]:
        return await asyncio.gather(*[agent_id_available("cache_hot_id") for _ in range(6)])

    results = asyncio.run(go())

    assert calls["n"] == 1  # six concurrent checks, one Soroban read
    assert all(r.reason == "id_taken" for r in results)
