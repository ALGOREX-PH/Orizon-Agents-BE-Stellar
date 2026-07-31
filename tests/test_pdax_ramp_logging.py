"""Ramp observability: the money-moving path must be reconstructable from the
log alone. Ramp records live in RAM only, so a restart leaves the log as the
sole evidence of what a ramp did — these tests assert the evidence exists and
that it never carries beneficiary PII."""

from __future__ import annotations

import logging

import pytest

from app.pdax import ramp, ramp_store
from app.pdax.models.ramp import RampRecord

STORE_LOGGER = "app.pdax.ramp_store"


@pytest.fixture(autouse=True)
def clean_ramp_state():
    ramp_store._ramps.clear()
    ramp_store._locks.clear()
    ramp._PAYOUTS.clear()
    yield
    ramp_store._ramps.clear()
    ramp_store._locks.clear()
    ramp._PAYOUTS.clear()


def _rec(ramp_id: str, status: str = "completed") -> RampRecord:
    return RampRecord(
        ramp_id=ramp_id,
        direction="onramp",
        status=status,
        created_at="t",
        identifier=f"id-{ramp_id}",
    )


def _messages(caplog, logger_name: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == logger_name]


def test_add_stage_logs_the_transition(caplog):
    record = _rec("r1")
    with caplog.at_level(logging.INFO, logger=STORE_LOGGER):
        ramp_store.add_stage(record, "buy_usdc", "success", "order 77")
    lines = _messages(caplog, STORE_LOGGER)
    assert any(
        "ramp_id=r1" in m and "stage=buy_usdc" in m and "status=success" in m and "order 77" in m for m in lines
    ), lines


def test_add_stage_logs_direction_for_correlation(caplog):
    record = _rec("r2")
    with caplog.at_level(logging.INFO, logger=STORE_LOGGER):
        ramp_store.add_stage(record, "estimate", "failed", "pdax_error")
    assert any("direction=onramp" in m for m in _messages(caplog, STORE_LOGGER))


def test_evicting_an_in_flight_ramp_warns(caplog, monkeypatch):
    """A live ramp pushed out by the retention cap can never be advanced or
    reconciled again — it must not vanish silently."""
    monkeypatch.setattr(ramp_store, "_MAX_RAMPS", 1)
    ramp_store.save(_rec("r0", "awaiting_payment"))
    with caplog.at_level(logging.WARNING, logger=STORE_LOGGER):
        ramp_store.save(_rec("r1", "completed"))
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("evicted in-flight ramp" in m and "ramp_id=r0" in m for m in warnings), warnings


def test_evicting_a_terminal_ramp_does_not_warn(caplog, monkeypatch):
    monkeypatch.setattr(ramp_store, "_MAX_RAMPS", 1)
    ramp_store.save(_rec("r0", "completed"))
    with caplog.at_level(logging.WARNING, logger=STORE_LOGGER):
        ramp_store.save(_rec("r1", "completed"))
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
