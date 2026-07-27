from __future__ import annotations

import asyncio
from collections import OrderedDict, defaultdict

from .schemas import TraceLine

# Remember at most this many finished tasks. Mirrors AppState.task_order's
# maxlen=200 retention bound so the set can't grow for the process lifetime.
_CLOSED_MAX = 200


class TraceBus:
    """Per-task asyncio.Queue fan-out for SSE subscribers.

    A task reaches an explicit terminal state via close(): late subscribers
    get a queue pre-loaded with the None sentinel instead of a queue no
    producer will ever feed, so their streams terminate immediately.
    """

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[TraceLine | None]]] = defaultdict(list)
        # Insertion-ordered capped set of finished task ids.
        self._closed: OrderedDict[str, None] = OrderedDict()

    def is_closed(self, task_id: str) -> bool:
        return task_id in self._closed

    def subscribe(self, task_id: str) -> asyncio.Queue[TraceLine | None]:
        q: asyncio.Queue[TraceLine | None] = asyncio.Queue()
        if task_id in self._closed:
            q.put_nowait(None)  # already finished — terminate immediately
            return q
        self._subs[task_id].append(q)
        return q

    def unsubscribe(self, task_id: str, q: asyncio.Queue[TraceLine | None]) -> None:
        subs = self._subs.get(task_id)
        if subs is None:
            return
        if q in subs:
            subs.remove(q)
        if not subs:
            # defaultdict would otherwise keep re-created empty lists forever.
            del self._subs[task_id]

    async def publish(self, task_id: str, line: TraceLine) -> None:
        for q in list(self._subs.get(task_id, [])):
            await q.put(line)

    async def close(self, task_id: str) -> None:
        # Mark terminal BEFORE waking subscribers so a concurrent subscribe
        # can never land in _subs after the sentinel sweep.
        self._closed[task_id] = None
        self._closed.move_to_end(task_id)
        while len(self._closed) > _CLOSED_MAX:
            self._closed.popitem(last=False)
        for q in list(self._subs.get(task_id, [])):
            await q.put(None)  # sentinel → end stream
        self._subs.pop(task_id, None)


bus = TraceBus()
