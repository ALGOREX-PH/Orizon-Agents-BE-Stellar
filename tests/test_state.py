"""Bounded retention in AppState — tasks, traces, and plans must not grow
without bound on a long-lived single-worker process, and eviction prefers
terminal tasks so a still-running workflow is never dropped mid-stream."""

from __future__ import annotations

from app.schemas import Plan, StoredPlan, Task, TaskStatus, TraceLine
from app.state import AppState


def _task(i: int, status: TaskStatus = "complete") -> Task:
    return Task(
        id=f"tsk_{i:04d}",
        intent="build something",
        agents=1,
        spent=0.1,
        status=status,
        started="just now",
    )


def _plan(i: int) -> StoredPlan:
    return StoredPlan(
        id=f"pln_{i:04d}",
        intent="build something",
        plan=Plan(steps=[]),
        total_usdc=0.0,
        total_eta=0.0,
    )


def test_tasks_and_traces_evicted_beyond_capacity():
    s = AppState()
    cap = s.task_order.maxlen
    assert cap is not None
    overflow = 5
    for i in range(cap + overflow):
        t = _task(i)
        s.add_task(t)
        s.append_trace(t.id, TraceLine(t="00:00", level="exec", msg="step"))
        s.task_tokens[t.id] = f"tok_{i:04d}"

    assert len(s.task_order) == cap
    assert len(s.tasks) == cap
    assert len(s.traces) == cap
    assert len(s.task_tokens) == cap
    # The oldest ids are gone from every structure...
    for i in range(overflow):
        gone = f"tsk_{i:04d}"
        assert gone not in s.tasks
        assert gone not in s.traces
        assert gone not in s.task_order
        assert gone not in s.task_tokens
    # ...and the newest survive, traces intact.
    newest = f"tsk_{cap + overflow - 1:04d}"
    assert newest in s.tasks
    assert len(s.traces[newest]) == 1
    assert s.task_tokens[newest] == f"tok_{cap + overflow - 1:04d}"


def test_eviction_prefers_terminal_tasks():
    s = AppState()
    cap = s.task_order.maxlen
    assert cap is not None
    # The three OLDEST tasks are still running; everything after is terminal.
    for i in range(cap):
        s.add_task(_task(i, status="running" if i < 3 else "complete"))

    s.add_task(_task(cap))

    # The oldest terminal task went; every running workflow survived.
    assert f"tsk_{3:04d}" not in s.tasks
    for i in range(3):
        assert s.tasks[f"tsk_{i:04d}"].status == "running"
    assert f"tsk_{cap:04d}" in s.tasks
    assert len(s.tasks) == cap
    assert len(s.task_order) == cap


def test_eviction_falls_back_to_oldest_when_all_running():
    s = AppState()
    cap = s.task_order.maxlen
    assert cap is not None
    for i in range(cap):
        s.add_task(_task(i, status="running"))

    s.add_task(_task(cap, status="running"))

    # Nothing terminal to shed — the oldest overall goes so the cap holds.
    assert f"tsk_{0:04d}" not in s.tasks
    assert f"tsk_{1:04d}" in s.tasks
    assert f"tsk_{cap:04d}" in s.tasks
    assert len(s.tasks) == cap
    assert len(s.task_order) == cap


def test_plans_bounded():
    s = AppState()
    cap = s.plan_order.maxlen
    assert cap is not None
    overflow = 3
    for i in range(cap + overflow):
        s.add_plan(_plan(i))

    assert len(s.plan_order) == cap
    assert len(s.plans) == cap
    for i in range(overflow):
        assert f"pln_{i:04d}" not in s.plans
    assert f"pln_{cap + overflow - 1:04d}" in s.plans


def test_recent_tasks_unaffected():
    s = AppState()
    for i in range(30):
        s.add_task(_task(i))
    recent = s.recent_tasks(limit=10)
    assert [t.id for t in recent] == [f"tsk_{i:04d}" for i in range(29, 19, -1)]
