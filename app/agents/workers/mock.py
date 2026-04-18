from __future__ import annotations

import asyncio
import random
from typing import Any

from .base import Worker


class MockWorker(Worker):
    real = False

    def __init__(self, id_: str, name: str) -> None:
        self.id = id_
        self.name = name

    async def run(self, intent: str, rationale: str) -> dict[str, Any]:
        await asyncio.sleep(0.2 + random.random() * 0.4)
        return {
            "summary": f"{self.name} simulated output for intent",
            "mock": True,
            "intent_excerpt": intent[:80],
        }
