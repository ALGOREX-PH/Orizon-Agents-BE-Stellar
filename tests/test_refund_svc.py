"""Story 4.01 — partial-credit refund mechanism (app/services/refund_svc.py).

Pins the settler-funded-credit design: the derived dispute job id that clears
the ReputationLedger replay guard (R12), the stated credit-amount policy, and
that the two settler-signed invocations are built with the right arguments (a
SAC transfer settler→buyer, and a dispute rating under the derived id).
"""

from __future__ import annotations

import asyncio
import hashlib

import app.stellar.client as sc
from app.services import refund_svc


def test_dispute_job_id_is_deterministic_16_bytes_and_distinct() -> None:
    jid = bytes(range(16))
    d = refund_svc.dispute_job_id(jid)
    assert isinstance(d, bytes) and len(d) == 16
    assert d == refund_svc.dispute_job_id(jid)  # deterministic
    assert d != jid  # not the settled job's id (clears the replay guard)
    assert d == hashlib.sha256(jid + b"dispute").digest()[:16]  # documented derivation


def test_dispute_job_id_differs_per_job() -> None:
    a = refund_svc.dispute_job_id(bytes(16))
    b = refund_svc.dispute_job_id(bytes([1]) + bytes(15))
    assert a != b


def test_credited_amount_full_partial_and_clamped() -> None:
    assert refund_svc.credited_amount_usdc(0.054) == 0.054  # default fraction 1.0
    assert refund_svc.credited_amount_usdc(0.10, 0.5) == 0.05
    assert refund_svc.credited_amount_usdc(0.10, 2.0) == 0.10  # fraction clamped to 1.0
    assert refund_svc.credited_amount_usdc(0.10, -1.0) == 0.0  # fraction clamped to 0
    assert refund_svc.credited_amount_usdc(-5.0) == 0.0  # negative charge floored
