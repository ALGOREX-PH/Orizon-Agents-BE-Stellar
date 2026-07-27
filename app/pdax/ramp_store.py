"""
In-memory ramp store.

Holds `RampRecord`s for the lifetime of the process (mirrors the app's other
in-memory state). Retention is bounded like app/state.py: the store is
insertion-ordered with a hard cap — when full, the oldest TERMINAL
(completed/failed) ramp is evicted first, falling back to the oldest overall,
and the matching per-ramp lock (and any payout stash) goes with it. A
production deployment would back this with a database so ramps survive
restarts and can be reconciled against PDAX webhooks.
"""
from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from datetime import datetime, timezone

from .models.ramp import RampRecord, RampStage

# Retention cap for tracked ramps (insertion-ordered eviction, see save()).
_MAX_RAMPS = 500
_TERMINAL = frozenset({"completed", "failed"})

_ramps: OrderedDict[str, RampRecord] = OrderedDict()
_locks: dict[str, asyncio.Lock] = {}


def lock_for(ramp_id: str) -> asyncio.Lock:
    """Per-ramp lock so a duplicate/racing webhook can't advance it twice."""
    lock = _locks.get(ramp_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[ramp_id] = lock
    return lock


def new_id() -> str:
    return f"ramp_{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(record: RampRecord) -> RampRecord:
    if record.ramp_id not in _ramps and len(_ramps) >= _MAX_RAMPS:
        _evict_one()
    _ramps[record.ramp_id] = record
    return record


def _evict_one() -> None:
    """Drop one ramp to make room: the oldest terminal (completed/failed) one,
    or — if every ramp is somehow still in flight — the oldest overall, so the
    store can never exceed its cap."""
    victim = next(
        (rid for rid, r in _ramps.items() if r.status in _TERMINAL),
        next(iter(_ramps)),
    )
    _ramps.pop(victim, None)
    _locks.pop(victim, None)
    # Late import (ramp imports this module) — an evicted in-flight off-ramp
    # must not leave its payout PII stranded in the stash.
    from . import ramp

    ramp._PAYOUTS.pop(victim, None)


def get(ramp_id: str) -> RampRecord | None:
    return _ramps.get(ramp_id)


def list_all() -> list[RampRecord]:
    return list(_ramps.values())


def find_by_identifier(identifier: str) -> RampRecord | None:
    for r in _ramps.values():
        if r.identifier == identifier:
            return r
    return None


def add_stage(record: RampRecord, name: str, status: str, detail: str = "") -> None:
    record.stages.append(RampStage(name=name, status=status, detail=detail))
