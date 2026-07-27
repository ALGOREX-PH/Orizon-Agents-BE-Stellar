"""
Tiny TTL cache for read-only Soroban simulate calls.

FE polling hits the read routes with identical params every second or two;
each hit costs a full simulate round-trip to Soroban RPC. A short TTL cache
(seconds) collapses those into one upstream call without serving stale data
for longer than a poll interval.

Single-event-loop safe: entries are read/written only from the loop thread
(the awaited producer runs in a worker thread, but the dict mutation happens
after the await, back on the loop). Failures are never cached.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

_store: dict[str, tuple[float, Any]] = {}

# Single-flight: concurrent misses on one key serialize on a per-key lock so
# only the first caller runs the producer; the rest are served the cached
# result on re-check. Locks live on the loop thread only.
_locks: dict[str, asyncio.Lock] = {}

# Sweep threshold: entries are only overwritten, never evicted, so a stream of
# unique keys would grow the dict forever. Past this size, misses sweep expired
# entries out.
_MAX_ENTRIES = 512


async def get_or_set(
    key: str,
    ttl_seconds: float,
    producer: Callable[[], Awaitable[Any]],
) -> Any:
    """Return the cached value for `key` if fresh, else await `producer()`.

    Only successful results are cached; if `producer` raises, the exception
    propagates and nothing is stored.
    """
    hit = _store.get(key)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        # Re-check: while we waited for the lock, the first flight may have
        # produced and cached the value.
        now = time.monotonic()
        hit = _store.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
        if len(_store) > _MAX_ENTRIES:
            for k in [k for k, (exp, _) in _store.items() if exp <= now]:
                del _store[k]
            for k in [k for k, lk in _locks.items() if k != key and not lk.locked()]:
                del _locks[k]
        value = await producer()
        _store[key] = (time.monotonic() + ttl_seconds, value)
        return value


def clear() -> None:
    """Drop all cached entries (used by tests)."""
    _store.clear()
    _locks.clear()
