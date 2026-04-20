from __future__ import annotations

from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from ...config import settings
from .base import Worker


class ArtifactFile(BaseModel):
    path: str
    language: str  # "html" | "css" | "js" | "tsx" | "python"
    content: str


class CodeArtifact(BaseModel):
    title: str = Field(..., max_length=80)
    summary: str = Field(..., max_length=280)
    files: list[ArtifactFile] = Field(..., min_length=1, max_length=5)
    entry: str = Field(..., description="Path of the main file, matches one of files[].path")
    preview_html: str = Field(
        ..., description="Self-contained HTML document for the sandboxed preview iframe"
    )


def coerce_artifact(content: Any) -> CodeArtifact:
    """
    Accept either a CodeArtifact instance, a dict, or a JSON string and
    return a CodeArtifact.

    gpt-5.3-codex + Agno sometimes hands back content as a raw JSON string
    (or a string wrapped in ```json fences``` from the reasoning model's
    draft format) rather than as a parsed Pydantic object. This normalises
    both shapes without failing the workflow.
    """
    import json
    import re

    if isinstance(content, CodeArtifact):
        return content
    if isinstance(content, dict):
        return CodeArtifact.model_validate(content)
    if isinstance(content, str):
        s = content.strip()
        # Strip ```json ... ``` or ``` ... ``` fences if present
        fence = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", s, re.DOTALL)
        if fence:
            s = fence.group(1).strip()
        # Try direct JSON parse
        try:
            return CodeArtifact.model_validate_json(s)
        except Exception:
            pass
        # Try to find the first balanced JSON object in the string
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            try:
                return CodeArtifact.model_validate(json.loads(m.group(0)))
            except Exception as e:
                raise ValueError(
                    f"code.gen returned unparseable JSON: {str(e)[:160]}"
                ) from e
        raise ValueError(
            f"code.gen returned a string without JSON object (first 160 chars): {s[:160]}"
        )
    raise TypeError(f"unexpected code.gen content type: {type(content).__name__}")


INSTRUCTIONS = """You are Orizon's code-generation agent — the best coding agent in the
network. Your output must feel like something shipped by a senior product
engineer at a design-led studio, not a demo.

# Deliverable

A self-contained SINGLE-FILE HTML artifact that runs by saving to `index.html`
and opening it in a browser — zero build step, zero network calls.

# Hard constraints (never violate)

1. ONE file. Inline ALL CSS in a single `<style>` in `<head>`. Inline ALL JS in
   a single `<script>` just before `</script></body>`.
2. NO external assets: no CDN fonts, no remote images, no imported modules,
   no analytics. Everything is inline. Use system font stack or well-chosen
   web-safe families (`"Inter", "SF Pro Text", system-ui, sans-serif`).
   For icons, inline `<svg>` — never emoji-as-icon unless intentional.
3. Include `<meta charset="utf-8">` and
   `<meta name="viewport" content="width=device-width,initial-scale=1">`.
4. `html, body { height: 100%; margin: 0 }`. Use flexbox on `<body>` to center
   the app — it must render correctly inside a NARROW iframe, not just
   fullscreen.
5. Must ACTUALLY work end-to-end: every button wired, every keyboard
   shortcut live, every calculation correct, every timer tick precise,
   every game playable. If you would show a placeholder in a mockup, build
   the real thing instead.

# Quality bar — state of the art

- **Depth over minimalism.** Ship a feature-complete app, not a toy.
  - Calculator: basic + scientific ops, keyboard support, history panel,
    copy-to-clipboard on result, memory (M+, M-, MR, MC), theme toggle.
  - Pomodoro: work/short break/long break cycles, configurable durations,
    cycle counter, pause/resume, desktop notification via `Notification` API
    (guard for permission), session stats in `localStorage`.
  - Todo: add/edit/delete/reorder (drag + drop), filter (all/active/done),
    bulk actions, persist to `localStorage`, keyboard shortcuts, empty state.
  - Game: scoring, high score persisted, difficulty levels, pause, restart,
    keyboard + touch input, subtle juice (screen shake, particle on hit,
    pitched sound via `AudioContext`).
  - Landing page: hero, feature grid with real copy, pricing / CTA, testimonial,
    FAQ (accessible `<details>`), subtle parallax, scroll-linked reveal.

- **Design.** Tasteful dark UI by default unless the intent asks otherwise.
  Use a small design-system in CSS variables:
  `--bg, --surface, --surface-2, --border, --text, --muted, --accent,
   --accent-2, --radius, --shadow, --easing`. Include a 200ms ease curve for
  transitions. Accent with a single gradient (violet → cyan is on-brand).
  Elevation via `box-shadow` + `backdrop-filter: blur(12px)` where it fits.

- **Motion.** Every interactive element has a transition (≤ 200ms). Entry
  animations via `@keyframes` when appropriate. Respect
  `@media (prefers-reduced-motion: reduce)` — kill animations for a11y.

- **Accessibility.** Semantic HTML (`<main>`, `<nav>`, `<button>`, `<label>`).
  Real focus-visible outlines (`outline: 2px solid var(--accent)`). ARIA
  labels on icon-only buttons. Keyboard parity for every mouse action.
  Color contrast WCAG AA or better.

- **Responsive.** Works ≥320px. Use clamp() for fluid type. Touch targets
  ≥ 40px. No horizontal overflow.

- **State + persistence.** Non-trivial state lives in `localStorage` under a
  namespaced key (e.g. `orizon.calculator.v1`). Wrap reads in try/catch.

- **Code quality.** Zero globals (wrap in an IIFE or use `let` inside module
  scope). Event delegation over per-element listeners where it helps. Pure
  helpers for formatting. Use `dataset` instead of class toggling for state.
  Small, readable functions with descriptive names.

# Length target

~400–700 lines of well-commented, production-quality code. Favor depth and
polish over brevity; do not pad.

# OUTPUT SHAPE

Return a CodeArtifact with:
- `title`: confident product-style name — "Pulse Pomodoro", "Aurora Calc".
- `summary`: one punchy sentence describing what it does + the one thing
  that makes it feel premium.
- `files`: single entry `{path: "index.html", language: "html", content: <full HTML>}`.
- `entry`: "index.html".
- `preview_html`: EXACT same string as files[0].content.
"""


class CodeGen(Worker):
    id = "agt_11c0"
    name = "code.gen"
    real = True

    def __init__(self) -> None:
        self._agent = Agent(
            name="code.gen",
            model=OpenAIChat(
                id=settings.worker_model,
                api_key=settings.openai_api_key,
                reasoning_effort=settings.code_reasoning_effort,
                temperature=settings.code_temperature,
            ),
            instructions=INSTRUCTIONS,
            output_schema=CodeArtifact,
        )

    def _artifact_dict(self, out: CodeArtifact) -> dict[str, Any]:
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

    async def run(self, intent: str, rationale: str) -> dict[str, Any]:
        # Lazy import — avoids a hard dependency cycle between code_gen ↔ code_critic
        # at module-load time (code_critic re-imports CodeArtifact from here).
        from .code_critic import CodeCritic
        from .code_validator import validate_html

        # ── 1. Draft ───────────────────────────────────────────────────
        prompt = f"INTENT: {intent}\nRATIONALE: {rationale}\n\nReturn the CodeArtifact."
        result = await self._agent.arun(prompt)
        draft: CodeArtifact = result.content  # type: ignore[assignment]
        draft_art = self._artifact_dict(draft)
        draft_html = draft_art["preview_html"]

        # ── 2. Validate ────────────────────────────────────────────────
        violations = validate_html(draft_html)

        # ── 3. Critic refinement (always runs — even with 0 violations,
        #     the critic pushes the output from "senior draft" to "shipped") ─
        critic_notes: list[str] = []
        final_art = draft_art
        try:
            critic = CodeCritic()
            revised = await critic.refine(
                intent=intent,
                rationale=rationale,
                draft_html=draft_html,
                violations=violations,
            )
            revised_html = revised["preview_html"]
            post_violations = validate_html(revised_html)
            if post_violations and len(post_violations) >= len(violations):
                # Critic didn't actually improve things — fall back to draft.
                critic_notes.append(
                    f"critic skipped: {len(post_violations)} remaining violations"
                )
            else:
                draft_lines = draft_html.count("\n")
                revised_lines = revised_html.count("\n")
                delta = revised_lines - draft_lines
                critic_notes.append(
                    f"draft {draft_lines}L → revised {revised_lines}L ({'+' if delta >= 0 else ''}{delta})"
                )
                final_art = revised
        except Exception as e:  # pragma: no cover — never fail the whole workflow
            critic_notes.append(f"critic failed: {type(e).__name__}: {str(e)[:80]}")

        final_bytes = sum(len(f["content"]) for f in final_art["files"])
        return {
            "summary": final_art["title"] + " — " + final_art["summary"],
            "artifact": final_art,
            "counts": {
                "files": len(final_art["files"]),
                "bytes": final_bytes,
                "notes": critic_notes,
            },
            "critic_violations": violations,
            "critic_notes": critic_notes,
        }
