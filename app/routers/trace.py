from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from ..schemas import TraceLine
from ..state import state
from ..trace_bus import bus

router = APIRouter(tags=["trace"])


@router.get("/trace/{task_id}", response_model=list[TraceLine])
async def get_trace(task_id: str) -> list[TraceLine]:
    if task_id not in state.traces and task_id not in state.tasks:
        raise HTTPException(404, f"unknown task: {task_id}")
    return state.traces.get(task_id, [])


@router.get("/trace/{task_id}/stream")
async def stream_trace(task_id: str, request: Request) -> EventSourceResponse:
    """Server-Sent Events — replays the existing trace then streams live lines."""
    if task_id not in state.traces and task_id not in state.tasks:
        raise HTTPException(404, f"unknown task: {task_id}")

    queue = bus.subscribe(task_id)

    async def generator():
        try:
            # Replay anything already recorded so late subscribers see full history.
            for line in state.traces.get(task_id, []):
                yield {"event": "trace", "data": line.model_dump_json()}

            while True:
                if await request.is_disconnected():
                    break
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # keepalive
                    yield {"event": "ping", "data": "{}"}
                    continue

                if line is None:
                    yield {"event": "done", "data": "{}"}
                    break
                yield {"event": "trace", "data": line.model_dump_json()}
        finally:
            bus.unsubscribe(task_id, queue)

    return EventSourceResponse(generator())
