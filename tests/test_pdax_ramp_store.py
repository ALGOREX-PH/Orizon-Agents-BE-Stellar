"""Bounded ramp store: hard cap, terminal-first eviction, lock + payout
cleanup on eviction."""

from __future__ import annotations

import pytest

from app.pdax import ramp, ramp_store
from app.pdax.models.ramp import RampRecord


@pytest.fixture(autouse=True)
def clean_ramp_state():
    ramp_store._ramps.clear()
    ramp_store._locks.clear()
    ramp._PAYOUTS.clear()
    yield
    ramp_store._ramps.clear()
    ramp_store._locks.clear()
    ramp._PAYOUTS.clear()


def _rec(i: int, status: str = "completed") -> RampRecord:
    return RampRecord(ramp_id=f"r{i}", direction="onramp", status=status, created_at="t")


def test_store_never_exceeds_cap(monkeypatch):
    monkeypatch.setattr(ramp_store, "_MAX_RAMPS", 5)
    for i in range(20):
        ramp_store.save(_rec(i))
        assert len(ramp_store._ramps) <= 5
    assert len(ramp_store.list_all()) == 5
    # Newest survive.
    assert ramp_store.get("r19") is not None


def test_eviction_prefers_oldest_terminal(monkeypatch):
    monkeypatch.setattr(ramp_store, "_MAX_RAMPS", 3)
    ramp_store.save(_rec(0, "completed"))
    ramp_store.save(_rec(1, "awaiting_payment"))
    ramp_store.save(_rec(2, "failed"))
    ramp_store.save(_rec(3, "quoted"))  # forces one eviction
    assert ramp_store.get("r0") is None  # oldest terminal went first
    assert ramp_store.get("r1") is not None  # in-flight ramp survived
    assert ramp_store.get("r2") is not None
    assert ramp_store.get("r3") is not None


def test_eviction_falls_back_to_oldest_when_none_terminal(monkeypatch):
    monkeypatch.setattr(ramp_store, "_MAX_RAMPS", 2)
    ramp_store.save(_rec(0, "awaiting_payment"))
    ramp_store.save(_rec(1, "converting"))
    ramp_store.save(_rec(2, "quoted"))
    assert ramp_store.get("r0") is None
    assert len(ramp_store._ramps) == 2


def test_eviction_drops_lock_and_payout(monkeypatch):
    monkeypatch.setattr(ramp_store, "_MAX_RAMPS", 1)
    ramp_store.save(_rec(0, "completed"))
    ramp_store.lock_for("r0")
    ramp._PAYOUTS["r0"] = object()  # stand-in for a stashed OffRampRequest
    ramp_store.save(_rec(1, "completed"))
    assert "r0" not in ramp_store._locks
    assert "r0" not in ramp._PAYOUTS
    assert ramp_store.get("r1") is not None


def test_resaving_existing_ramp_does_not_evict(monkeypatch):
    monkeypatch.setattr(ramp_store, "_MAX_RAMPS", 2)
    ramp_store.save(_rec(0, "awaiting_payment"))
    ramp_store.save(_rec(1, "awaiting_payment"))
    updated = _rec(1, "completed")
    ramp_store.save(updated)  # same id — an update, not an insert
    assert len(ramp_store._ramps) == 2
    assert ramp_store.get("r0") is not None
    assert ramp_store.get("r1").status == "completed"
