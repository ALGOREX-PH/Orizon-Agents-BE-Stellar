"""
Tiny TTL cache for read-only Soroban simulate calls.

FE polling hits the read routes with identical params every second or two;
each hit costs a full simulate round-trip to Soroban RPC. A short TTL cache
(seconds) collapses those into one upstream call without serving stale data
for longer than a poll interval.

Single-event-loop safe: entries are read/written only from the loop thread
(the producer may hop into a worker thread, but every dict mutation happens
back on the loop).

Concurrency model — single-flight with shield:
  - The first miss on a key spawns a real asyncio.Task for the producer and
    registers it per key; concurrent misses await the same flight.
  - Callers await the flight through asyncio.shield, so a cancelled caller
    (e.g. a batch read hitting its deadline) does NOT cancel the flight: the
    underlying work keeps running and its result still lands in the cache
    for the next request instead of being re-spawned from scratch.
  - Producer failures are negatively cached for a short window so a
    hard-down RPC doesn't fan out a fresh upstream call per request: within
    the window an equivalent exception is raised without spawning work.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

_store: dict[str, tuple[float, Any]] = {}

# In-flight producers: key → the Task computing that key's value.
_flights: dict[str, asyncio.Task[Any]] = {}

# Negative cache: key → (expiry, exception class, message). Hits within the
# window raise a FRESH instance — retaining live exception objects would pin
# their tracebacks (and captured frames) in memory, and re-raising the same
# object appends traceback frames on every hit.
_failures: dict[str, tuple[float, type[BaseException], str]] = {}
_NEGATIVE_TTL_SECONDS = 2.5

# Sweep threshold: entries are only overwritten, never evicted, so a stream of
# unique keys would grow the dicts forever. Past this combined size, misses
# sweep expired entries out. The gate counts _failures too: an attacker
# streaming unique failing keys (or a hard-down RPC) populates only the
# negative cache, and _store alone would never trip the sweep. (Flights
# self-clean via their done callbacks.)
_MAX_ENTRIES = 512


async def get_or_set(
    key: str,
    ttl_seconds: float,
    producer: Callable[[], Awaitable[Any]],
) -> Any:
    """Return the cached value for `key` if fresh, else await the producer.

    Successful results are cached for `ttl_seconds`. Failures are cached for
    `_NEGATIVE_TTL_SECONDS` and re-raised on hits within that window.
    """
    now = time.monotonic()
    hit = _store.get(key)
    if hit is not None and hit[0] > now:
        return hit[1]
    neg = _failures.get(key)
    if neg is not None:
        expiry, exc_type, message = neg
        if expiry > now:
            raise _rebuild(exc_type, message)
        del _failures[key]
    task = _flights.get(key)
    if task is None or task.done():
        if len(_store) + len(_failures) > _MAX_ENTRIES:
            _sweep(now)
        task = asyncio.create_task(_produce(key, ttl_seconds, producer))
        _flights[key] = task
        task.add_done_callback(partial(_on_flight_done, key))
    # shield: a cancelled caller must not cancel the shared flight — the
    # producer keeps running and its result still lands in the cache.
    return await asyncio.shield(task)


async def _produce(key: str, ttl_seconds: float, producer: Callable[[], Awaitable[Any]]) -> Any:
    try:
        value = await producer()
    except Exception as e:
        _failures[key] = (time.monotonic() + _NEGATIVE_TTL_SECONDS, type(e), str(e))
        raise
    _store[key] = (time.monotonic() + ttl_seconds, value)
    return value


def _rebuild(exc_type: type[BaseException], message: str) -> BaseException:
    """Fresh exception instance for a negative-cache hit.

    Preserves the original class when it's constructible from its message
    (the common case); classes with other constructor signatures fall back to
    a RuntimeError naming the original type.
    """
    try:
        return exc_type(message)
    except Exception:
        return RuntimeError(f"{exc_type.__name__}: {message}")


def _on_flight_done(key: str, task: asyncio.Task[Any]) -> None:
    if _flights.get(key) is task:
        del _flights[key]
    if not task.cancelled():
        # Mark a failure as retrieved even if every caller was cancelled
        # before it landed; the exception lives on in the negative cache.
        task.exception()


def _sweep(now: float) -> None:
    for k in [k for k, (exp, _) in _store.items() if exp <= now]:
        del _store[k]
    for k in [k for k, entry in _failures.items() if entry[0] <= now]:
        del _failures[k]


def clear() -> None:
    """Drop all cached entries, failures, and flight registrations (tests)."""
    _store.clear()
    _failures.clear()
    _flights.clear()
