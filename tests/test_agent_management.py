"""Story 1.08 — operator agent-management build endpoints.

`build/update-price` and `build/set-active` mirror `build_register_agent`:
owner-signed unsigned XDR, charset + price validation at the router edge, a
plain 404 for an unregistered id, and `owner_account_unfunded` decoded from the
build. Ownership itself is the contract's `require_auth`, not re-checked here.
Ids are unique per test and the read cache is cleared so existence checks can't
leak across tests.
"""

from __future__ import annotations

import pytest
from stellar_sdk.exceptions import AccountNotFoundException

import app.stellar.client as sc
from app.stellar import cache as rcache

_OWNER = "GA7AI5TAJEZA27I666DSJC4MUJYBEWUYNNZWPU7R2ONA7IZQVO6R5OQV"


@pytest.fixture(autouse=True)
def _clear_cache() -> object:
    rcache.clear()
    yield
    rcache.clear()


def _exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """The registry read succeeds → the agent exists on-chain."""
    monkeypatch.setattr(sc, "simulate_read", lambda *a, **k: {"id": "op_one", "owner": _OWNER})


def _missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_k: object) -> object:
        raise RuntimeError("no such agent")

    monkeypatch.setattr(sc, "simulate_read", _raise)


# ── update-price ────────────────────────────────────────────────
def test_update_price_builds_xdr_for_a_registered_agent(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _exists(monkeypatch)
    monkeypatch.setattr(sc, "build_invoke_xdr", lambda *a, **k: "AAAA-update-xdr")
    r = client.post(
        "/api/stellar/build/update-price",
        json={"owner": _OWNER, "agent_id": "op_one", "price_usdc": 0.08},
    )
    assert r.status_code == 200
    assert r.json()["xdr"] == "AAAA-update-xdr"


def test_update_price_is_404_for_an_unregistered_agent(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _missing(monkeypatch)
    r = client.post(
        "/api/stellar/build/update-price",
        json={"owner": _OWNER, "agent_id": "op_ghost", "price_usdc": 0.08},
    )
    assert r.status_code == 404
    assert "agent_not_found" in r.text


def test_update_price_rejects_a_malformed_id(client) -> None:
    r = client.post(
        "/api/stellar/build/update-price",
        json={"owner": _OWNER, "agent_id": "has-a-hyphen", "price_usdc": 0.08},
    )
    assert r.status_code == 422


def test_update_price_rejects_a_non_positive_price(client) -> None:
    r = client.post(
        "/api/stellar/build/update-price",
        json={"owner": _OWNER, "agent_id": "op_one", "price_usdc": 0},
    )
    assert r.status_code == 422


def test_update_price_names_an_unfunded_owner(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _exists(monkeypatch)

    def _unfunded(*_a: object, **_k: object) -> object:
        raise AccountNotFoundException("account not found")

    monkeypatch.setattr(sc, "build_invoke_xdr", _unfunded)
    r = client.post(
        "/api/stellar/build/update-price",
        json={"owner": _OWNER, "agent_id": "op_one", "price_usdc": 0.08},
    )
    assert r.status_code == 400
    assert "owner_account_unfunded" in r.text


# ── set-active (delist / relist) ────────────────────────────────
def test_set_active_delists_and_relists(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _exists(monkeypatch)
    monkeypatch.setattr(sc, "build_invoke_xdr", lambda *a, **k: "AAAA-setactive-xdr")
    for active in (False, True):
        r = client.post(
            "/api/stellar/build/set-active",
            json={"owner": _OWNER, "agent_id": "op_one", "active": active},
        )
        assert r.status_code == 200
        assert r.json()["xdr"] == "AAAA-setactive-xdr"


def test_set_active_is_404_for_an_unregistered_agent(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _missing(monkeypatch)
    r = client.post(
        "/api/stellar/build/set-active",
        json={"owner": _OWNER, "agent_id": "op_ghost", "active": False},
    )
    assert r.status_code == 404
    assert "agent_not_found" in r.text


def test_set_active_rejects_a_malformed_id(client) -> None:
    r = client.post(
        "/api/stellar/build/set-active",
        json={"owner": _OWNER, "agent_id": "bad id", "active": False},
    )
    assert r.status_code == 422
