"""GET /api/pdax/ramp: pagination bounds and account-number masking."""

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


def _save(i: int) -> None:
    ramp_store.save(RampRecord(ramp_id=f"r{i}", direction="onramp", status="completed", created_at="t"))


def test_ramp_list_paginates(client):
    for i in range(7):
        _save(i)
    r = client.get("/api/pdax/ramp?limit=3&offset=2")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 7
    assert [x["ramp_id"] for x in body["ramps"]] == ["r2", "r3", "r4"]


def test_ramp_list_limit_capped_at_200(client):
    r = client.get("/api/pdax/ramp?limit=201")
    assert r.status_code == 422


def test_ramp_list_default_limit(client):
    for i in range(60):
        _save(i)
    r = client.get("/api/pdax/ramp")
    assert len(r.json()["ramps"]) == 50


def test_ramp_list_masks_account_numbers(client, monkeypatch):
    class _FakeRecord:
        def model_dump(self) -> dict:
            return {
                "ramp_id": "r1",
                "beneficiary_account_number": "1234567890",
                "payout": {"account_number": "9876543210"},
                "stages": [{"detail": "ok"}],
            }

    monkeypatch.setattr("app.pdax.ramp_store.list_all", lambda: [_FakeRecord()])
    r = client.get("/api/pdax/ramp")
    assert r.status_code == 200
    ramp_dump = r.json()["ramps"][0]
    assert ramp_dump["beneficiary_account_number"] == "****7890"
    assert ramp_dump["payout"]["account_number"] == "****3210"
    assert "1234567890" not in r.text
    assert "9876543210" not in r.text
