"""Failure paths of the execution service: a workflow that raises or is
cancelled must land in status="failed" and always close its trace stream, and
every per-step failure must reach the server log — trace lines alone are
invisible once the task is evicted."""

from __future__ import annotations

import asyncio
import logging

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


def _svc_errors(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.services.execution_svc" and r.levelno >= logging.ERROR]


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


def test_step_exception_is_logged_with_context_and_traceback(monkeypatch, caplog):
    class BoomWorker:
        name = "w.boom"

        async def run(self, intent, rationale, context=None):
            raise RuntimeError("openai: invalid_api_key")

    monkeypatch.setattr(execution_svc, "get_worker", lambda agent_id: BoomWorker())
    task_id = "tsk_step_log_exc"
    _add_task(task_id)

    with caplog.at_level(logging.ERROR, logger="app.services.execution_svc"):
        asyncio.run(execution_svc._run(_plan("pln_step_log_exc"), task_id))

    records = _svc_errors(caplog)
    assert records, "a swallowed step failure was never logged"
    msg = records[0].getMessage()
    # Diagnosable without a debugger: which task, which agent, which worker,
    # what the provider said — plus the traceback.
    assert task_id in msg
    assert "agt_x" in msg
    assert "w.boom" in msg
    assert "openai: invalid_api_key" in msg
    assert records[0].exc_info is not None


def test_step_timeout_is_logged(monkeypatch, caplog):
    class HangingWorker:
        name = "w.hang"

        async def run(self, intent, rationale, context=None):
            await asyncio.sleep(30)

    monkeypatch.setattr(execution_svc, "get_worker", lambda agent_id: HangingWorker())
    monkeypatch.setattr(execution_svc, "STEP_TIMEOUT_SECONDS", 0.05)
    task_id = "tsk_step_log_timeout"
    _add_task(task_id)

    with caplog.at_level(logging.ERROR, logger="app.services.execution_svc"):
        asyncio.run(execution_svc._run(_plan("pln_step_log_timeout"), task_id))

    records = _svc_errors(caplog)
    assert records, "a swallowed step timeout was never logged"
    msg = records[0].getMessage()
    assert task_id in msg
    assert "w.hang" in msg
    assert "timed out" in msg


def test_unknown_agent_step_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(execution_svc, "get_worker", lambda agent_id: None)
    task_id = "tsk_step_log_unknown"
    _add_task(task_id)

    with caplog.at_level(logging.ERROR, logger="app.services.execution_svc"):
        asyncio.run(execution_svc._run(_plan("pln_step_log_unknown"), task_id))

    records = _svc_errors(caplog)
    assert records, "an unknown agent was never logged"
    msg = records[0].getMessage()
    assert task_id in msg
    assert "agt_x" in msg
    assert "unknown agent" in msg


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
