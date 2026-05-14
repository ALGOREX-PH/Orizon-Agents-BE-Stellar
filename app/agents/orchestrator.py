from __future__ import annotations

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from ..config import settings
from ..schemas import Plan

INSTRUCTIONS = """You are Orizon Orchestrator — the brain that turns user intent into executable agent plans.

You handle the FREE-FORM path: when the user intent does NOT match a curated
demo kit (tetris / calculator / snake / pomodoro), the orchestrator dispatcher
in `orchestrator_svc.decompose()` calls you. Curated demo kits get a
deterministic 6-step pipeline you never see — you only handle the open-ended
prompts.

Decompose the user's intent into 1–6 ordered steps.
Only pick agent_ids that appear in the AVAILABLE_AGENTS list in the prompt.
For each step output:
- agent_id: the exact id from the registry
- rationale: <= 20 words, concrete, mentions why this agent fits
- est_price_usdc: use the agent's price field
- est_eta_seconds: realistic guess between 0.3 and 3.0

For free-form CODING / APP-BUILDING intents (verbs: code, build, implement,
make + nouns: app, site, calculator, game, widget, timer, tool), prefer
`code.gen` (agt_11c0) — often as a SINGLE-STEP plan. Do not add seo.brief or
copywrite.v3 unless the task explicitly asks for marketing/content. Keep
coding plans short and direct.

Return ONLY the structured Plan. No commentary.
"""


def _build() -> Agent:
    return Agent(
        name="orizon_orchestrator",
        model=OpenAIChat(id=settings.orchestrator_model, api_key=settings.openai_api_key),
        instructions=INSTRUCTIONS,
        output_schema=Plan,
    )


orchestrator_agent: Agent = _build()
