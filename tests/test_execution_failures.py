"""Failure paths of the execution service: a workflow that raises or is
cancelled must land in status="failed" and always close its trace stream."""
from __future__ import annotations

import asyncio

import pytest

from app.schemas import Plan, PlanStep, StoredPlan, Task
from app.services import execution_svc
from app.state import state
from app.trace_bus import bus


def _plan(plan_id: str) -> StoredPlan:
    return StoredPlan(
        id=plan_id,
        intent="exercise the failure path",
        plan=Plan(
            steps=[
                PlanStep(
                    agent_id="agt_x",
                    agent_name="w.x",
                    rationale="r",
                    est_price_usdc=0.01,
                    est_eta_seconds=1.0,
                )
            ]
        ),
        total_usdc=0.01,
        total_eta=1.0,
    )


def _add_task(task_id: str) -> None:
    state.add_task(
        Task(
            id=task_id,
            intent="exercise the failure path",
            agents=1,
            spent=0.0,
            status="running",
            started="just now",
        )
    )


def _drain(q: asyncio.Queue) -> list:
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    return items


def test_mid_run_exception_marks_task_failed(monkeypatch):
    def boom(agent_id):
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(execution_svc, "get_worker", boom)
    task_id = "tsk_fail_exc"
    _add_task(task_id)

    async def run():
        q = bus.subscribe(task_id)
        await execution_svc._run(_plan("pln_fail_exc"), task_id)
        return q

    q = asyncio.run(run())
    assert state.tasks[task_id].status == "failed"
    lines = _drain(q)
    assert lines[-1] is None  # SSE terminator: bus.close ran
    errors = [ln for ln in lines if ln is not None and ln.level == "error"]
    assert any("workflow failed: registry exploded" in ln.msg for ln in errors)
    assert task_id not in bus._subs


def test_cancelled_run_marks_task_failed_and_closes_bus(monkeypatch):
    class SlowWorker:
        name = "w.slow"

        async def run(self, intent, rationale, context=None):
            await asyncio.sleep(30)

    monkeypatch.setattr(execution_svc, "get_worker", lambda agent_id: SlowWorker())
    task_id = "tsk_fail_cancel"
    _add_task(task_id)

    async def run():
        q = bus.subscribe(task_id)
        t = asyncio.create_task(execution_svc._run(_plan("pln_fail_cancel"), task_id))
        await asyncio.sleep(0.05)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
        return q

    q = asyncio.run(run())
    assert state.tasks[task_id].status == "failed"
    lines = _drain(q)
    assert lines[-1] is None  # cleanup survived the cancellation
    errors = [ln for ln in lines if ln is not None and ln.level == "error"]
    assert any("workflow cancelled" in ln.msg for ln in errors)
    assert task_id not in bus._subs
