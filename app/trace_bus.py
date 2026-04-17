from __future__ import annotations

import asyncio
from collections import defaultdict

from .schemas import TraceLine


class TraceBus:
    """Per-task asyncio.Queue fan-out for SSE subscribers."""

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[TraceLine | None]]] = defaultdict(list)

    def subscribe(self, task_id: str) -> asyncio.Queue[TraceLine | None]:
        q: asyncio.Queue[TraceLine | None] = asyncio.Queue()
        self._subs[task_id].append(q)
        return q

    def unsubscribe(self, task_id: str, q: asyncio.Queue[TraceLine | None]) -> None:
        if q in self._subs.get(task_id, []):
            self._subs[task_id].remove(q)

    async def publish(self, task_id: str, line: TraceLine) -> None:
        for q in list(self._subs.get(task_id, [])):
            await q.put(line)

    async def close(self, task_id: str) -> None:
        for q in list(self._subs.get(task_id, [])):
            await q.put(None)  # sentinel → end stream
        self._subs.pop(task_id, None)


bus = TraceBus()
