from __future__ import annotations

from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from ...config import settings
from .base import Worker


class Finding(BaseModel):
    claim: str = Field(..., max_length=200)
    confidence: float = Field(..., ge=0, le=1)


class ResearchOutput(BaseModel):
    findings: list[Finding] = Field(..., min_length=3, max_length=6)
    sources: list[str] = Field(..., max_length=6)
    summary: str = Field(..., max_length=300)


class ResearchPro(Worker):
    id = "agt_09l5"
    name = "research.pro"
    real = True

    def __init__(self) -> None:
        self._agent = Agent(
            name="research.pro",
            model=OpenAIChat(id=settings.worker_model, api_key=settings.openai_api_key),
            instructions=(
                "You are a research synthesis agent. Given an intent, return 3–6 findings "
                "(each a concrete claim + 0..1 confidence), 2–6 plausible source descriptors "
                "(short strings, no fabricated URLs), and a one-paragraph summary. Mark "
                "confidence low when a claim is speculative."
            ),
            output_schema=ResearchOutput,
        )

    async def run(self, intent: str, rationale: str) -> dict[str, Any]:
        prompt = f"INTENT: {intent}\nRATIONALE: {rationale}\n\nReturn the research brief."
        result = await self._agent.arun(prompt)
        out: ResearchOutput = result.content  # type: ignore[assignment]
        return {
            "summary": out.summary,
            "findings": [f.model_dump() for f in out.findings],
            "sources": out.sources,
            "counts": {"findings": len(out.findings), "sources": len(out.sources)},
        }
