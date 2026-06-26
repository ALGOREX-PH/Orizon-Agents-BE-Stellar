"""
In-memory ramp store.

Holds `RampRecord`s for the lifetime of the process (mirrors the app's other
in-memory state). A production deployment would back this with a database so
ramps survive restarts and can be reconciled against PDAX webhooks.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from .models.ramp import RampRecord, RampStage

_ramps: dict[str, RampRecord] = {}
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
    _ramps[record.ramp_id] = record
    return record


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
