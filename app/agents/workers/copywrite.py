from __future__ import annotations

from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from ...config import settings
from .base import Worker


class Section(BaseModel):
    title: str
    body: str = Field(..., max_length=280)


class CopyOutput(BaseModel):
    hero_headline: str
    hero_subtitle: str
    sections: list[Section] = Field(..., min_length=2, max_length=5)


class Copywrite(Worker):
    id = "agt_01h8"
    name = "copywrite.v3"
    real = True

    def __init__(self) -> None:
        self._agent = Agent(
            name="copywrite.v3",
            model=OpenAIChat(id=settings.worker_model, api_key=settings.openai_api_key),
            instructions=(
                "You are a senior marketing copywriter. Given an intent, draft a hero "
                "headline (<=80 chars), a hero subtitle (<=160 chars), and 3–4 landing "
                "sections with a title and short body each. Punchy, concrete, outcome-focused."
            ),
            output_schema=CopyOutput,
        )

    async def run(self, intent: str, rationale: str) -> dict[str, Any]:
        prompt = f"INTENT: {intent}\nRATIONALE: {rationale}\n\nDraft the copy."
        result = await self._agent.arun(prompt)
        out: CopyOutput = result.content  # type: ignore[assignment]
        return {
            "summary": out.hero_headline,
            "hero": {"headline": out.hero_headline, "subtitle": out.hero_subtitle},
            "sections": [s.model_dump() for s in out.sections],
            "counts": {"sections": len(out.sections)},
        }
