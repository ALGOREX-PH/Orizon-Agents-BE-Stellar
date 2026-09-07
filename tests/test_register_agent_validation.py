"""Story 1.03 — the register/authorize build models reject what the chain
would reject BEFORE the user signs: Symbol-charset ids and skills die at the
router as 422s, and a duplicate agent id is refused as a 409 by a preflight
read instead of surfacing as the on-chain AlreadyExists after signature."""

import pytest

from app.stellar import client as sc

# A real, checksum-valid strkey (the suite's standard test address) — the
# fail-open path reaches sc.addr(), which validates more than the regex.
_OWNER = "GA7AI5TAJEZA27I666DSJC4MUJYBEWUYNNZWPU7R2ONA7IZQVO6R5OQV"

_BODY = {
    "owner": _OWNER,
    "agent_id": "w1_ok",
    "name": "Agent",
    "skills": ["code"],
    "price_usdc": 0.1,
}


def _register(client, **over):
    return client.post("/api/stellar/build/register-agent", json={**_BODY, **over})


@pytest.mark.parametrize("bad", ["has-hyphen", "has.dot", "ünicode", "a" * 33, ""])
def test_register_rejects_non_symbol_agent_ids(client, bad):
    assert _register(client, agent_id=bad).status_code == 422


def test_register_rejects_non_symbol_skills(client):
    assert _register(client, skills=["ok", "bad-skill"]).status_code == 422


def test_authorize_rejects_a_non_symbol_agent_id(client):
    r = client.post(
        "/api/stellar/build/authorize",
        json={"payer": _OWNER, "agent_id": "bad-id", "max_amount_usdc": 1.0},
    )
    assert r.status_code == 422


def test_register_refuses_a_taken_id_before_signing(client, monkeypatch):
    # The preflight read succeeding means the id exists on-chain.
    monkeypatch.setattr(sc, "simulate_read", lambda *a, **k: {"id": "w1_ok"})
    r = _register(client)
    assert r.status_code == 409
    assert "agent_id_taken" in r.text


def test_register_fails_open_when_the_preflight_read_fails(client, monkeypatch):
    # A raising read means "unknown id or RPC down" — either way the build
    # proceeds; the chain's AlreadyExists stays the real guard.
    def _raise(*a, **k):
        raise RuntimeError("rpc unreachable")

    monkeypatch.setattr(sc, "simulate_read", _raise)
    monkeypatch.setattr(sc, "build_invoke_xdr", lambda *a, **k: "AAAA-fake-xdr")
    r = _register(client)
    assert r.status_code == 200
    assert r.json()["xdr"] == "AAAA-fake-xdr"
