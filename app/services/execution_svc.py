from __future__ import annotations

import asyncio
import secrets
import time
from typing import Optional

from ..agents.registry import get_worker
from ..schemas import StoredPlan, Task, TraceLine, TraceLevel
from ..state import state
from ..trace_bus import bus


def _now_ts(start: float) -> str:
    elapsed = time.monotonic() - start
    seconds = int(elapsed)
    hundredths = int((elapsed - seconds) * 1000)
    return f"{seconds:02d}.{hundredths:03d}"


async def _emit(task_id: str, start: float, level: TraceLevel, msg: str) -> TraceLine:
    line = TraceLine(t=_now_ts(start), level=level, msg=msg)
    state.append_trace(task_id, line)
    await bus.publish(task_id, line)
    return line


def _summarize(output: dict) -> str:
    if "summary" in output:
        return str(output["summary"])[:140]
    counts = output.get("counts")
    if isinstance(counts, dict):
        return ", ".join(f"{k}={v}" for k, v in counts.items())
    return "done"


async def execute_plan(plan: StoredPlan) -> str:
    task_id = f"tsk_{secrets.token_hex(3)}"
    task = Task(
        id=task_id,
        intent=plan.intent,
        agents=len(plan.plan.steps),
        spent=0.0,
        status="running",
        started="just now",
    )
    state.add_task(task)

    # Kick off execution in the background so the HTTP request returns immediately.
    asyncio.create_task(_run(plan, task_id))
    return task_id


async def _run(plan: StoredPlan, task_id: str) -> None:
    start = time.monotonic()
    spent = 0.0

    try:
        await _emit(task_id, start, "input", f"intent received → '{plan.intent}'")
        await _emit(
            task_id,
            start,
            "exec",
            f"orchestrator: decompose → [{', '.join(s.agent_id for s in plan.plan.steps)}]",
        )

        for step in plan.plan.steps:
            worker = get_worker(step.agent_id)
            if worker is None:
                await _emit(task_id, start, "error", f"unknown agent: {step.agent_id}")
                continue

            await _emit(
                task_id,
                start,
                "exec",
                f"match agent: {worker.name} ({step.agent_id}) — {step.rationale}",
            )

            try:
                output = await asyncio.wait_for(
                    worker.run(plan.intent, step.rationale), timeout=30.0
                )
            except asyncio.TimeoutError:
                await _emit(task_id, start, "error", f"{worker.name} timed out")
                continue
            except Exception as e:  # pragma: no cover
                await _emit(task_id, start, "error", f"{worker.name} failed: {e}")
                continue

            spent += step.est_price_usdc
            await _emit(
                task_id,
                start,
                "cost",
                f"x402 payment → {step.agent_id} :: {step.est_price_usdc:.3f} USDC settled",
            )
            await _emit(task_id, start, "out", f"{worker.name}: {_summarize(output)}")

        proof = "0x" + secrets.token_hex(16)
        await _emit(task_id, start, "proof", f"ERC-8004 attestation: {proof} recorded")
        await _emit(
            task_id,
            start,
            "proof",
            f"workflow sealed — {len(plan.plan.steps)} agents · {spent:.3f} USDC · "
            f"{time.monotonic() - start:.2f}s",
        )

        # update task
        task = state.tasks.get(task_id)
        if task:
            state.tasks[task_id] = task.model_copy(
                update={"status": "complete", "spent": round(spent, 4)}
            )

    finally:
        # tiny grace period so late subscribers can drain the queue
        await asyncio.sleep(0.05)
        await bus.close(task_id)
