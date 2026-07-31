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


def test_fresh_unique_keys_stay_bounded():
    """The case expiry-only sweeping could not handle.

    Cache keys are caller-influenced (`agent:{id}`, `repstate:{id}`,
    `attestation:{hex}` — unbounded distinct values), so a stream of unique
    keys that are ALL still fresh is reachable. Sweeping only expired entries
    freed nothing here: both dicts grew without bound and every later miss
    paid an O(n) scan that reclaimed nothing.
    """
    producer, _ = _counting_producer()

    async def run():
        for i in range(cache._MAX_ENTRIES * 3):
            await cache.get_or_set(f"fresh{i}", 60.0, producer)

    asyncio.run(run())
    assert len(cache._store) <= cache._MAX_ENTRIES + 1
    # Eviction is by expiry, and equal TTLs make that insertion order: the
    # newest writes survive and the oldest are gone.
    assert f"fresh{cache._MAX_ENTRIES * 3 - 1}" in cache._store
    assert "fresh0" not in cache._store


def test_eviction_drops_the_entries_closest_to_expiry_first():
    producer, _ = _counting_producer()

    async def run():
        # Written first, but with far more life left than anything that
        # follows — remaining TTL, not age, decides who goes.
        await cache.get_or_set("keep", 3600.0, producer)
        for i in range(cache._MAX_ENTRIES + 128):
            await cache.get_or_set(f"short{i}", 5.0, producer)

    asyncio.run(run())
    assert len(cache._store) <= cache._MAX_ENTRIES + 1
    assert "keep" in cache._store


def test_fresh_entries_and_failures_are_capped_together():
    """The cap is on the combined size: neither dict can be starved into
    unboundedness by the other filling up with fresh entries."""
    producer, _ = _counting_producer()

    async def failing():
        raise RuntimeError("rpc down")

    async def run():
        for i in range(cache._MAX_ENTRIES):
            await cache.get_or_set(f"fresh{i}", 60.0, producer)
        for i in range(cache._MAX_ENTRIES):
            with pytest.raises(RuntimeError):
                await cache.get_or_set(f"bad{i}", 60.0, failing)

    asyncio.run(run())
    assert len(cache._store) + len(cache._failures) <= cache._MAX_ENTRIES + 1


def test_sweep_runs_rarely_once_the_cache_is_full(monkeypatch):
    """Evicting to a low-water mark instead of exactly to the cap keeps the
    ordering pass off the hot path — otherwise every single miss past the
    threshold would pay for one, trading a memory leak for a CPU cliff."""
    producer, _ = _counting_producer()
    sweeps = {"n": 0}
    real_sweep = cache._sweep

    def counting_sweep(now: float) -> None:
        sweeps["n"] += 1
        real_sweep(now)

    monkeypatch.setattr(cache, "_sweep", counting_sweep)
    admissions = cache._MAX_ENTRIES * 2

    async def run():
        for i in range(admissions):
            await cache.get_or_set(f"fresh{i}", 60.0, producer)

    asyncio.run(run())
    # One sweep per _EVICT_HEADROOM admissions, not one per miss.
    assert sweeps["n"] <= admissions // cache._EVICT_HEADROOM + 2


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


def test_unique_failure_flood_stays_bounded(monkeypatch):
    """A stream of unique failing keys (attacker-reachable via unknown-id
    reads) must not grow the negative cache without bound — the sweep gate
    counts _failures even when _store stays empty (RPC hard down)."""
    monkeypatch.setattr(cache, "_NEGATIVE_TTL_SECONDS", 0.0)

    async def failing():
        raise RuntimeError("rpc down")

    async def run():
        for i in range(cache._MAX_ENTRIES + 64):
            with pytest.raises(RuntimeError):
                await cache.get_or_set(f"bad{i}", 60.0, failing)

    asyncio.run(run())
    assert len(cache._store) == 0
    assert len(cache._failures) <= cache._MAX_ENTRIES + 1


def test_negative_cache_reraises_fresh_instance():
    original = RuntimeError("rpc down")

    async def failing():
        raise original

    async def run():
        with pytest.raises(RuntimeError) as first:
            await cache.get_or_set("k", 60.0, failing)
        assert first.value is original  # the flight delivers the real exception
        with pytest.raises(RuntimeError) as second:
            await cache.get_or_set("k", 60.0, failing)
        # The negative-cache hit raises a FRESH object — re-raising the same
        # instance would append traceback frames on every hit and pin the
        # original traceback in memory.
        assert second.value is not original
        assert str(second.value) == "rpc down"

    asyncio.run(run())


def test_negative_cache_preserves_exception_class():
    async def failing():
        raise ValueError("bad param")

    async def run():
        with pytest.raises(ValueError, match="bad param"):
            await cache.get_or_set("k", 60.0, failing)
        with pytest.raises(ValueError, match="bad param"):
            await cache.get_or_set("k", 60.0, failing)

    asyncio.run(run())


def test_negative_cache_falls_back_for_odd_constructors():
    """Exception classes not constructible from a message re-raise as a
    RuntimeError naming the original type instead of blowing up the cache."""

    class TwoArg(Exception):
        def __init__(self, a: int, b: int) -> None:
            super().__init__(a, b)

    async def failing():
        raise TwoArg(1, 2)

    async def run():
        with pytest.raises(TwoArg):
            await cache.get_or_set("k", 60.0, failing)
        with pytest.raises(RuntimeError) as info:
            await cache.get_or_set("k", 60.0, failing)
        assert "TwoArg" in str(info.value)

    asyncio.run(run())


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
