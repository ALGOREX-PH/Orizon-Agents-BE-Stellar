"""Artifact retrieval and the simulated x402 payment flow."""

from __future__ import annotations

from app.schemas import Task
from app.state import state


def test_artifact_unknown_task_404(client):
    r = client.get("/api/tasks/tsk_missing/artifact")
    assert r.status_code == 404


def test_artifact_returned_for_stored_task(client):
    task = Task(
        id="tsk_artifact_test",
        intent="build a demo page",
        agents=1,
        spent=0.25,
        status="complete",
        started="just now",
        artifact={"title": "Demo", "files": []},
        charge_tx="charge123",
        proof_tx="proof456",
    )
    state.add_task(task)
    try:
        r = client.get(f"/api/tasks/{task.id}/artifact")
        assert r.status_code == 200
        body = r.json()
        assert body["artifact"] == {"title": "Demo", "files": []}
        assert body["charge_tx"] == "charge123"
        assert body["proof_tx"] == "proof456"
    finally:
        # Leave shared app state exactly as we found it.
        state.tasks.pop(task.id, None)
        state.traces.pop(task.id, None)
        try:
            state.task_order.remove(task.id)
        except ValueError:
            pass


def test_x402_challenges_without_payment_header(client):
    r = client.post(
        "/api/payments/x402",
        json={"agent_id": "agt_01h8", "amount_usdc": 1.5},
    )
    assert r.status_code == 402
    assert r.json() == {"status": "402", "receipt": None}
    assert r.headers["x-orizon-payment-required"] == "amount=1.500;agent=agt_01h8;token=USDC"


def test_x402_settles_with_payment_header(client):
    r = client.post(
        "/api/payments/x402",
        json={"agent_id": "agt_01h8", "amount_usdc": 1.5},
        headers={"X-Orizon-Payment": "sim-payment"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "paid"
    # receipt is "0x" + 10 random bytes hex-encoded
    assert body["receipt"].startswith("0x")
    assert len(body["receipt"]) == 22
