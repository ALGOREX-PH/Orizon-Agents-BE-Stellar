"""Unit tests for the Soroban read cache (TTL, sweep, shielded single-flight,
negative caching)."""
from __future__ import annotations

import asyncio

import pytest

from app.stellar import cache


@pytest.fixture(autouse=True)
def clean_cache():
    cache.clear()
    yield
    cache.clear()


def _counting_producer(value: str = "v", delay: float = 0.0):
    calls = {"n": 0}

    async def producer():
        calls["n"] += 1
        if delay:
            await asyncio.sleep(delay)
        return value

    return producer, calls


def test_hit_within_ttl_calls_producer_once():
    producer, calls = _counting_producer()

    async def run():
        first = await cache.get_or_set("k", 60.0, producer)
        second = await cache.get_or_set("k", 60.0, producer)
        return first, second

    first, second = asyncio.run(run())
    assert first == second == "v"
    assert calls["n"] == 1


def test_expired_entry_calls_producer_again():
    producer, calls = _counting_producer()

    async def run():
        await cache.get_or_set("k", 0.01, producer)
        await asyncio.sleep(0.03)
        return await cache.get_or_set("k", 0.01, producer)

    assert asyncio.run(run()) == "v"
    assert calls["n"] == 2


def test_sweep_drops_expired_keys_past_threshold():
    producer, _ = _counting_producer()

    async def run():
        # ttl 0 → every entry is expired the moment it lands.
        for i in range(cache._MAX_ENTRIES + 8):
            await cache.get_or_set(f"k{i}", 0.0, producer)
        # This miss crosses the threshold and sweeps the dead entries out.
        await cache.get_or_set("fresh", 60.0, producer)

    asyncio.run(run())
    assert len(cache._store) <= cache._MAX_ENTRIES
    assert "fresh" in cache._store


def test_concurrent_misses_share_one_producer_call():
    producer, calls = _counting_producer(delay=0.05)

    async def run():
        return await asyncio.gather(
            cache.get_or_set("k", 60.0, producer),
            cache.get_or_set("k", 60.0, producer),
        )

    results = asyncio.run(run())
    assert results == ["v", "v"]
    assert calls["n"] == 1


def test_producer_failure_is_negatively_cached():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        raise RuntimeError("rpc down")

    async def run():
        with pytest.raises(RuntimeError):
            await cache.get_or_set("k", 60.0, flaky)
        # Within the negative TTL the cached failure re-raises without
        # spawning any new upstream work.
        with pytest.raises(RuntimeError):
            await cache.get_or_set("k", 60.0, flaky)

    asyncio.run(run())
    assert calls["n"] == 1


def test_negative_cache_expires(monkeypatch):
    monkeypatch.setattr(cache, "_NEGATIVE_TTL_SECONDS", 0.03)
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("rpc down")
        return "ok"

    async def run():
        with pytest.raises(RuntimeError):
            await cache.get_or_set("k", 60.0, flaky)
        await asyncio.sleep(0.06)
        return await cache.get_or_set("k", 60.0, flaky)

    assert asyncio.run(run()) == "ok"
    assert calls["n"] == 2


def test_cancelled_caller_still_caches():
    producer, calls = _counting_producer(delay=0.05)

    async def run():
        caller = asyncio.create_task(cache.get_or_set("k", 60.0, producer))
        await asyncio.sleep(0.01)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        # The flight survived the cancelled caller and its result landed in
        # the cache — the next get is a hit, not a fresh producer run.
        await asyncio.sleep(0.1)
        return await cache.get_or_set("k", 60.0, producer)

    assert asyncio.run(run()) == "v"
    assert calls["n"] == 1


def test_second_caller_joins_flight_after_first_cancelled():
    producer, calls = _counting_producer(delay=0.05)

    async def run():
        first = asyncio.create_task(cache.get_or_set("k", 60.0, producer))
        await asyncio.sleep(0.01)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        # A caller arriving while the orphaned flight is still running joins
        # it instead of spawning a second producer.
        return await cache.get_or_set("k", 60.0, producer)

    assert asyncio.run(run()) == "v"
    assert calls["n"] == 1
