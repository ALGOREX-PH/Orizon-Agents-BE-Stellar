from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Worker(ABC):
    id: str
    name: str
    real: bool

    @abstractmethod
    async def run(self, intent: str, rationale: str) -> dict[str, Any]:
        """Execute the agent's task; return a small dict describing the output."""
        raise NotImplementedError
