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
6. NEVER use JavaScript `eval()` or `new Function()`. Real parsers only.

# Quality bar — state of the art

- **Depth over minimalism.** Ship a feature-complete app, not a toy.
  Default examples (override if the user prompt is more specific):
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

- **Design.** Tasteful UI grounded in the DESIGN TOKENS (if provided in the
  prompt). Use a small design-system in CSS variables matching the supplied
  palette. Include a 200ms ease curve for transitions. Elevation via
  `box-shadow` + `backdrop-filter: blur(12px)` where it fits.

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

# Using the upstream context

When the prompt includes BRAND / FEATURES / DESIGN_TOKENS sections, treat them
as **non-negotiable**:
- Use the BRAND name as the artifact `title`.
- Implement EVERY feature listed in FEATURES (do not collapse or skip).
- Use the DESIGN_TOKENS palette as the literal CSS variable values — copy the
  `:root { --bg: …; --primary: …; }` block verbatim.
- Use the DESIGN_TOKENS family_ui and family_display as the actual `font-family`
  declarations.

A KIT_NOTES section (when present) is the technical playbook for the build —
follow its recommended structure, key handlers, and visual polish notes
closely. The kit notes were written by a senior engineer who knows what the
shipping version looks like.

# Length target

For curated demo intents (kit context present), aim for **600–1000 lines** of
production-quality code — the kit deserves polish. For free-form intents,
**400–700 lines** is the sweet spot.

# OUTPUT SHAPE

Return a CodeArtifact with:
- `title`: confident product-style name. Use the brand name if provided.
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
        # NOTE: gpt-5.3-codex (and other reasoning-class models) reject the
        # `reasoning_effort` and `temperature` kwargs on the Chat Completions
        # endpoint. They have their own internal reasoning knobs. Omit both
        # and lean on the detailed prompt for quality. The polish pass now
        # runs as a separate top-level `code.critic` step in the pipeline.
        self._agent = Agent(
            name="code.gen",
            model=OpenAIChat(
                id=settings.worker_model,
                api_key=settings.openai_api_key,
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

    @staticmethod
    def _context_block(context: dict[str, Any] | None) -> str:
        """Format prior step outputs as plain-text sections to splice into the
        prompt. Each section is opt-in: missing pieces are silently skipped."""
        if not context:
            return ""

        parts: list[str] = []

        kit = context.get("kit")
        if isinstance(kit, dict):
            brand = kit.get("brand", {}) or {}
            parts.append(
                "## BRAND\n"
                f"- name: {brand.get('name', '')}\n"
                f"- tagline: {brand.get('tagline', '')}\n"
                f"- audience: {', '.join(brand.get('audience', []))}"
            )
            features = kit.get("features", []) or []
            if features:
                lines = "\n".join(
                    f"- {f['label']}: {f['detail']}" for f in features
                )
                parts.append(f"## FEATURES (implement every one)\n{lines}")

            addendum = kit.get("code_gen_addendum") or ""
            if addendum:
                parts.append(f"## KIT_NOTES\n{addendum}")

            min_lines = kit.get("expected_min_lines")
            if min_lines:
                parts.append(
                    f"## LENGTH_TARGET\nProduce at least {min_lines} lines of "
                    "production code; favor depth over brevity."
                )

        # Brand from seo.brief (only used if no kit was present)
        seo = context.get("seo.brief")
        if isinstance(seo, dict) and "## BRAND" not in "\n".join(parts):
            brand_name = seo.get("brand_name") or ""
            tagline = seo.get("tagline") or ""
            audiences = seo.get("audiences", []) or []
            if brand_name or tagline:
                parts.append(
                    "## BRAND\n"
                    f"- name: {brand_name}\n"
                    f"- tagline: {tagline}\n"
                    f"- audience: {', '.join(audiences)}"
                )

        # Feature brief from research.pro (only used if no kit features in prompt)
        research = context.get("research.pro")
        if (
            isinstance(research, dict)
            and "## FEATURES" not in "\n".join(parts)
        ):
            findings = research.get("findings", []) or []
            if findings:
                lines = "\n".join(
                    f"- {f.get('claim', '')}" for f in findings[:8]
                )
                parts.append(f"## FEATURES (research-derived)\n{lines}")

        # Design tokens from design.figma
        design = context.get("design.figma")
        if isinstance(design, dict):
            css = design.get("css_vars") or ""
            typo = design.get("typography", {}) or {}
            family_ui = typo.get("family_ui", "")
            family_display = typo.get("family_display", "")
            block = "## DESIGN_TOKENS\n"
            if css:
                block += f"Copy this :root block into your CSS verbatim:\n```\n{css}\n```\n"
            if family_ui or family_display:
                block += (
                    f"Font stacks:\n"
                    f"- family_ui: {family_ui}\n"
                    f"- family_display: {family_display}\n"
                )
            parts.append(block.rstrip())

        return "\n\n".join(parts)

    async def run(
        self,
        intent: str,
        rationale: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Lazy import — avoids a hard dependency cycle between code_gen ↔ code_validator
        from .code_validator import validate_html

        # ── Build the prompt with optional context sections ────────────────
        ctx_block = self._context_block(context)
        prompt_parts = [
            f"INTENT: {intent}",
            f"RATIONALE: {rationale}",
        ]
        if ctx_block:
            prompt_parts.append(ctx_block)
        prompt_parts.append("Return the CodeArtifact.")
        prompt = "\n\n".join(prompt_parts)

        # ── Draft ──────────────────────────────────────────────────────────
        result = await self._agent.arun(prompt)
        draft = coerce_artifact(result.content)
        draft_art = self._artifact_dict(draft)

        # ── Validate (no critic here — critic runs as a separate pipeline step) ─
        violations = validate_html(draft_art["preview_html"])

        final_bytes = sum(len(f["content"]) for f in draft_art["files"])
        final_lines = sum(f["content"].count("\n") + 1 for f in draft_art["files"])
        return {
            "summary": draft_art["title"] + " — " + draft_art["summary"],
            "artifact": draft_art,
            "counts": {
                "files": len(draft_art["files"]),
                "bytes": final_bytes,
                "lines": final_lines,
            },
            # Surface validator-detected issues so the next step (code.critic)
            # — and the trace log — can act on them.
            "validator_violations": violations,
        }
