from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Worker(ABC):
    id: str
    name: str
    real: bool

    @abstractmethod
    async def run(
        self,
        intent: str,
        rationale: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the agent's task; return a small dict describing the output.

        `context` carries forward results from prior pipeline steps and (when
        present) the curated `DemoKit` for the intent. Keys of interest:
          - context['kit']           → DemoKit dict (or None)
          - context['research.pro']  → prior research brief
          - context['seo.brief']     → prior brand block
          - context['design.figma']  → prior design tokens
          - context['code.gen']      → prior code artifact
        Workers are free to ignore the kwarg if they don't need context.
        """
        raise NotImplementedError
