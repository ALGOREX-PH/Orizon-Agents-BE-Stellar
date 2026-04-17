from __future__ import annotations

from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from ...config import settings
from .base import Worker


class SeoBriefOutput(BaseModel):
    keywords: list[str] = Field(..., max_length=12)
    audiences: list[str] = Field(..., max_length=5)
    summary: str


class SeoBrief(Worker):
    id = "agt_05x7"
    name = "seo.brief"
    real = True

    def __init__(self) -> None:
        self._agent = Agent(
            name="seo.brief",
            model=OpenAIChat(id=settings.worker_model, api_key=settings.openai_api_key),
            instructions=(
                "You are an SEO research agent. Given an intent, return a JSON brief with: "
                "8–12 high-intent keywords, 2–4 audience clusters (concise labels), and a "
                "one-line summary. Be concrete, skip fluff."
            ),
            output_schema=SeoBriefOutput,
        )

    async def run(self, intent: str, rationale: str) -> dict[str, Any]:
        prompt = f"INTENT: {intent}\nRATIONALE: {rationale}\n\nReturn the SEO brief."
        result = await self._agent.arun(prompt)
        out: SeoBriefOutput = result.content  # type: ignore[assignment]
        return {
            "summary": out.summary,
            "keywords": out.keywords,
            "audiences": out.audiences,
            "counts": {"keywords": len(out.keywords), "audiences": len(out.audiences)},
        }
