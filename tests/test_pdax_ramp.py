"""Ramp orchestration against a fake PdaxClient: off-ramp payout PII is
dropped once the advance step finishes (success or failure)."""
from __future__ import annotations

import asyncio

import pytest

from app.pdax import ramp, ramp_store
from app.pdax.errors import PdaxError
from app.pdax.models.ramp import OffRampRequest

VALID_G = "G" + "A" * 55

OFFRAMP_REQ = dict(
    usdc_amount="10",
    identifier="off-1",
    beneficiary_bank_code="BAUBPPH",
    beneficiary_account_name="Ada Lovelace",
    beneficiary_account_number="1234567890",
    sender_first_name="Ada",
    sender_last_name="Lovelace",
    beneficiary_first_name="Ada",
    beneficiary_last_name="Lovelace",
)


@pytest.fixture(autouse=True)
def clean_ramp_state():
    ramp_store._ramps.clear()
    ramp_store._locks.clear()
    ramp._PAYOUTS.clear()
    yield
    ramp_store._ramps.clear()
    ramp_store._locks.clear()
    ramp._PAYOUTS.clear()


def _quote(side: str) -> dict:
    return {
        "quote_id": "q1",
        "quote_currency": "USDC",
        "base_currency": "PHP",
        "side": side,
        "base_quantity": 10.0,
        "price": 58.0,
        "total_amount": 580.0,
    }


def _order(side: str) -> dict:
    return {
        "order_id": 77,
        "status": "filled",
        "quote_currency": "USDC",
        "base_currency": "PHP",
        "side": side,
        "base_quantity": 10.0,
        "price": 58.0,
        "total_amount": 580.0,
    }


class FakePdaxClient:
    """Dispatches client.request calls to canned responses by path suffix."""

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    async def request(self, method, path, *, params=None, json=None, authenticated=True):
        self.calls.append(path)
        for suffix, resp in self.responses.items():
            if path.endswith(suffix):
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unexpected PDAX call: {method} {path}")


def _offramp_client() -> FakePdaxClient:
    return FakePdaxClient(
        {
            "v2/trade/price": {"data": _quote("sell")},
            "v1/crypto/deposit": {
                "data": {"currency": "USDCXLM", "address": "GDEPOSIT", "tag": None}
            },
            "v2/trade/quote": {"data": _quote("sell")},
            "v1/trade": {"data": _order("sell")},
            "v1/fiat/withdraw": {
                "data": {
                    "request_id": "wr1",
                    "identifier": "off-1-payout",
                    "amount": 580.0,
                    "method": "PAY-TO-ACCOUNT-NON-REAL-TIME",
                    "status": "COMPLETED",
                }
            },
        }
    )


def test_offramp_payout_popped_after_completion():
    client = _offramp_client()

    async def run():
        record = await ramp.start_offramp(client, OffRampRequest(**OFFRAMP_REQ))
        assert record.status == "awaiting_payment"
        assert record.ramp_id in ramp._PAYOUTS  # PII held while in flight
        advanced = await ramp.advance_offramp(client, record)
        assert advanced.status == "completed"
        assert advanced.withdraw_request_id == "wr1"
        assert ramp._PAYOUTS == {}  # ...and dropped once settled

    asyncio.run(run())


def test_offramp_payout_popped_even_on_failure():
    client = _offramp_client()
    client.responses["v2/trade/quote"] = PdaxError(
        "Insufficient balance.", code="OT010006", http_status=400
    )

    async def run():
        record = await ramp.start_offramp(client, OffRampRequest(**OFFRAMP_REQ))
        advanced = await ramp.advance_offramp(client, record)
        assert advanced.status == "failed"
        assert ramp._PAYOUTS == {}  # dropped on the failure path too

    asyncio.run(run())


def test_advance_offramp_without_payout_fails_cleanly():
    client = _offramp_client()

    async def run():
        record = await ramp.start_offramp(client, OffRampRequest(**OFFRAMP_REQ))
        ramp._PAYOUTS.clear()  # simulate a restart losing the payout stash
        advanced = await ramp.advance_offramp(client, record)
        assert advanced.status == "failed"
        assert advanced.error == "missing payout details"

    asyncio.run(run())
