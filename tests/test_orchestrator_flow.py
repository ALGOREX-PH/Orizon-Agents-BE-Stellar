"""End-to-end offline flow: kit decompose → execute → artifact."""
from __future__ import annotations

import time


def test_kit_decompose_returns_deterministic_plan(client):
    r = client.post(
        "/api/orchestrator/decompose", json={"intent": "tetris game in html"}
    )
    assert r.status_code == 200
    plan = r.json()
    assert plan["plan_id"]
    assert len(plan["steps"]) >= 4
    assert plan["total_usdc"] > 0


def test_kit_execute_produces_baked_artifact(client):
    plan = client.post(
        "/api/orchestrator/decompose", json={"intent": "calculator web app"}
    ).json()
    task = client.post(
        "/api/orchestrator/execute", json={"plan_id": plan["plan_id"]}
    ).json()
    assert task["task_id"]

    artifact = None
    for _ in range(60):
        r = client.get(f"/api/tasks/{task['task_id']}/artifact").json()
        if r.get("artifact"):
            artifact = r["artifact"]
            break
        time.sleep(0.25)
    assert artifact is not None, "artifact never arrived"
    assert artifact["preview_html"]
    assert len(artifact["preview_html"]) > 10_000


def test_decompose_rejects_short_intent(client):
    r = client.post("/api/orchestrator/decompose", json={"intent": "hi"})
    assert r.status_code == 422
