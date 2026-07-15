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

import time
from typing import Any, Awaitable, Callable

_store: dict[str, tuple[float, Any]] = {}


async def get_or_set(
    key: str,
    ttl_seconds: float,
    producer: Callable[[], Awaitable[Any]],
) -> Any:
    """Return the cached value for `key` if fresh, else await `producer()`.

    Only successful results are cached; if `producer` raises, the exception
    propagates and nothing is stored.
    """
    now = time.monotonic()
    hit = _store.get(key)
    if hit is not None and hit[0] > now:
        return hit[1]
    value = await producer()
    _store[key] = (time.monotonic() + ttl_seconds, value)
    return value


def clear() -> None:
    """Drop all cached entries (used by tests)."""
    _store.clear()
