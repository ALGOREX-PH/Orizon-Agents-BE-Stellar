"""
Self-critique pass for code.gen.

Not a standalone Worker — invoked internally by code_gen.CodeGen.run().
Takes a draft HTML artifact + a list of violations from code_validator and
returns a revised, polished CodeArtifact.

This is where the "agents hire agents" premise pays off: the draft was
already senior-level; the critic pushes it to shipping-quality.
"""
from __future__ import annotations

from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from ...config import settings
from .code_gen import CodeArtifact, coerce_artifact  # reuse schema + JSON-string coercion

INSTRUCTIONS = """You are Orizon's senior code reviewer.

You receive a SINGLE-FILE HTML artifact that another agent drafted and
must return an IMPROVED version that ships. Your job is polish + hardening,
never stripping.

# Absolute rules

1. PRESERVE the overall concept, title, and user-facing behavior. Do not
   pivot the app into something else.
2. DO NOT remove features. Only add, tighten, or fix.
3. Fix EVERY item in the VIOLATIONS list. Each one is non-negotiable.
4. Output the same single-file HTML contract: one `<style>` in <head>,
   one `<script>` before </body>, zero external assets, correctly centered
   in a narrow iframe (html,body{height:100%;margin:0} + flex on body).

# What "improved" means here

- **Depth**: add missing quality-bar items (keyboard shortcuts, ARIA,
  empty/loading states, persistence, undo, confirmation dialogs, prefers-
  reduced-motion support, focus-visible outlines, WCAG AA contrast).
- **Polish**: tighten spacing, typography rhythm, micro-interactions,
  elevation, gradient accents. Prefer CSS variables for theme.
- **Readability**: clean up inlined JS — small named helpers, event
  delegation, dataset-driven state, no globals. Add brief comments to
  non-obvious logic.
- **Resilience**: wrap localStorage reads in try/catch, guard
  `Notification.requestPermission`, clamp input, handle empty collections.
- **Length**: 500–900 lines of well-commented production code is the
  sweet spot. Go longer only if the feature list demands it.

# Input shape

The user prompt contains three sections:
  INTENT: … original user intent
  VIOLATIONS: … bullet list from the validator (may be empty)
  DRAFT_HTML: … full current HTML source

# Output shape

Return a CodeArtifact with the SAME structure as the draft:
- `title`: keep or refine the original name.
- `summary`: one sentence capturing the improved version's edge.
- `files`: [{path: "index.html", language: "html", content: <full HTML>}].
- `entry`: "index.html".
- `preview_html`: EXACT same string as files[0].content.
"""


def _build_critic() -> Agent:
    return Agent(
        name="code.critic",
        model=OpenAIChat(
            id=settings.worker_model,
            api_key=settings.openai_api_key,
            reasoning_effort=settings.code_reasoning_effort,
            temperature=settings.code_temperature,
        ),
        instructions=INSTRUCTIONS,
        output_schema=CodeArtifact,
    )


class CodeCritic:
    """Lightweight wrapper around the Agno critic agent."""

    def __init__(self) -> None:
        self._agent = _build_critic()

    async def refine(
        self,
        intent: str,
        rationale: str,
        draft_html: str,
        violations: list[str],
    ) -> dict[str, Any]:
        viol_block = (
            "\n".join(f"  - {v}" for v in violations) if violations else "  (none)"
        )
        prompt = (
            f"INTENT: {intent}\n"
            f"RATIONALE: {rationale}\n"
            f"VIOLATIONS:\n{viol_block}\n\n"
            f"DRAFT_HTML:\n{draft_html}"
        )
        result = await self._agent.arun(prompt)
        out = coerce_artifact(result.content)

        preview = out.preview_html
        if not preview.strip():
            entry_file = next((f for f in out.files if f.path == out.entry), out.files[0])
            preview = entry_file.content

        return {
            "title": out.title,
            "summary": out.summary,
            "files": [f.model_dump() for f in out.files],
            "entry": out.entry,
            "preview_html": preview,
        }
