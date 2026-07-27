"""Capability-token task authorization. OFF (the default) keeps every read
public while execute already returns a read_token; ON demands the per-task
token (X-Task-Token header, or ?token= for EventSource), lets a valid
X-API-Key bypass, empties the task list, and answers 404 — never 403 — to
wrong or missing tokens so task ids stay unenumerable."""

from __future__ import annotations

import pytest

from app.config import settings
from app.schemas import Task, TraceLine
from app.state import state

TOKEN = "tok_task_auth_test"


def _seed_task(task_id: str) -> str:
    state.add_task(
        Task(
            id=task_id,
            intent="capability token demo",
            agents=1,
            spent=0.01,
            status="complete",
            started="now",
        )
    )
    state.task_tokens[task_id] = TOKEN
    state.append_trace(task_id, TraceLine(t="0.01", level="exec", msg="step"))
    return task_id


def _read_paths(task_id: str) -> list[str]:
    return [
        f"/api/tasks/{task_id}",
        f"/api/tasks/{task_id}/artifact",
        f"/api/trace/{task_id}",
    ]


@pytest.mark.parametrize("enforced", [False, True])
def test_execute_always_returns_read_token(client, monkeypatch, enforced):
    monkeypatch.setattr(settings, "task_auth_required", enforced)
    plan = client.post("/api/orchestrator/decompose", json={"intent": "pomodoro timer app"}).json()
    body = client.post("/api/orchestrator/execute", json={"plan_id": plan["plan_id"]}).json()
    assert body["read_token"]
    assert state.task_tokens[body["task_id"]] == body["read_token"]


def test_reads_public_and_task_listed_when_off(client):
    assert settings.task_auth_required is False
    tid = _seed_task("tsk_auth_off")
    for path in _read_paths(tid):
        assert client.get(path).status_code == 200
    listed = client.get("/api/tasks", params={"limit": 200}).json()
    assert tid in [t["id"] for t in listed]


def test_reads_404_without_or_with_wrong_token_when_on(client, monkeypatch):
    monkeypatch.setattr(settings, "task_auth_required", True)
    tid = _seed_task("tsk_auth_on_404")
    for path in _read_paths(tid) + [f"/api/trace/{tid}/stream"]:
        assert client.get(path).status_code == 404
        assert client.get(path, headers={"X-Task-Token": "wrong"}).status_code == 404


def test_reads_200_with_header_token_when_on(client, monkeypatch):
    monkeypatch.setattr(settings, "task_auth_required", True)
    tid = _seed_task("tsk_auth_on_hdr")
    for path in _read_paths(tid):
        assert client.get(path, headers={"X-Task-Token": TOKEN}).status_code == 200


def test_stream_accepts_query_token_when_on(client, monkeypatch):
    # EventSource cannot set headers, so the stream must take ?token=.
    monkeypatch.setattr(settings, "task_auth_required", True)
    tid = _seed_task("tsk_auth_on_sse")
    events: list[str] = []
    with client.stream("GET", f"/api/trace/{tid}/stream", params={"token": TOKEN}) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if line.startswith("event: done") or len(events) > 50:
                break
    assert events == ["trace", "done"]


def test_api_key_bypasses_task_tokens_when_on(client, monkeypatch):
    monkeypatch.setattr(settings, "task_auth_required", True)
    monkeypatch.setattr(settings, "api_key", "ops-key")
    tid = _seed_task("tsk_auth_on_ops")
    for path in _read_paths(tid):
        assert client.get(path, headers={"X-API-Key": "ops-key"}).status_code == 200
        assert client.get(path, headers={"X-API-Key": "not-the-key"}).status_code == 404


def test_task_list_empty_when_on(client, monkeypatch):
    monkeypatch.setattr(settings, "task_auth_required", True)
    _seed_task("tsk_auth_on_list")
    assert client.get("/api/tasks", params={"limit": 200}).json() == []


def test_unknown_task_stays_404_with_any_token_when_on(client, monkeypatch):
    monkeypatch.setattr(settings, "task_auth_required", True)
    assert client.get("/api/tasks/tsk_missing", headers={"X-Task-Token": TOKEN}).status_code == 404
