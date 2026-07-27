"""Bounded retention in AppState — tasks, traces, and plans must not grow
without bound on a long-lived single-worker process."""

from __future__ import annotations

from app.schemas import Plan, StoredPlan, Task, TraceLine
from app.state import AppState


def _task(i: int) -> Task:
    return Task(
        id=f"tsk_{i:04d}",
        intent="build something",
        agents=1,
        spent=0.1,
        status="complete",
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

    assert len(s.task_order) == cap
    assert len(s.tasks) == cap
    assert len(s.traces) == cap
    # The oldest ids are gone from every structure...
    for i in range(overflow):
        gone = f"tsk_{i:04d}"
        assert gone not in s.tasks
        assert gone not in s.traces
        assert gone not in s.task_order
    # ...and the newest survive, traces intact.
    newest = f"tsk_{cap + overflow - 1:04d}"
    assert newest in s.tasks
    assert len(s.traces[newest]) == 1


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
