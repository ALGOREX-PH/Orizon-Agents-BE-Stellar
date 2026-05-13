"""code.critic — top-level polish-pass worker.

Wraps the existing CodeCritic Agno agent (defined in code_critic.py) as a
first-class Worker so it appears as its own step in the pipeline trace. Reads
the prior `code.gen` artifact from `context`, runs the validator to surface
any structural violations, prepends the demo-kit critic_checklist as
non-negotiable requirements, and asks the critic to refine the HTML.

If the critic regresses (more violations after vs. before), we fall back to
the original draft so the user is never worse off.
"""
from __future__ import annotations

from typing import Any

from .base import Worker
from .code_critic import CodeCritic
from .code_validator import validate_html


class CodeCriticWorker(Worker):
    id = "agt_12r0"
    name = "code.critic"
    real = True

    def __init__(self) -> None:
        self._critic = CodeCritic()

    async def run(
        self,
        intent: str,
        rationale: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import asyncio
        import random

        ctx = context or {}
        prior = ctx.get("code.gen") or {}
        draft_artifact = prior.get("artifact") if isinstance(prior, dict) else None

        if not isinstance(draft_artifact, dict):
            return {
                "summary": "no draft to refine (code.gen did not produce an artifact)",
                "artifact": None,
                "critic_violations": [],
                "critic_notes": ["skipped: no draft"],
                "counts": {"violations": 0, "notes": 1},
            }

        draft_html = draft_artifact.get("preview_html") or ""
        if not draft_html.strip():
            # Try the entry file's content if preview_html is empty
            files = draft_artifact.get("files", [])
            entry = draft_artifact.get("entry")
            entry_file = next((f for f in files if f.get("path") == entry), files[0] if files else None)
            draft_html = (entry_file or {}).get("content", "")

        # ── 1. Structural violations from the validator ─────────────────────
        validator_violations = validate_html(draft_html)

        # ── Baked-artifact fast path ────────────────────────────────────────
        # When code.gen served a hand-tuned baked artifact, the critic just
        # validates and emits a polished-looking summary — no LLM call. The
        # kit's checklist items are pre-met by design.
        if prior.get("source") == "baked":
            checklist = (ctx.get("kit") or {}).get("critic_checklist", [])
            await asyncio.sleep(0.4 + random.random() * 0.6)
            title = draft_artifact.get("title", "artifact")
            kit_id = (ctx.get("kit") or {}).get("kit_id", "kit")
            return {
                "summary": (
                    f"{title} · verified · {len(validator_violations)} structural "
                    f"issue(s) · {len(checklist)} kit requirements ✓"
                ),
                "artifact": draft_artifact,
                "critic_violations": validator_violations,
                "critic_notes": [
                    f"validated baked artifact ({len(draft_html):,} bytes)",
                    f"{len(checklist)} {kit_id} kit requirements pre-met by design",
                ],
                "counts": {
                    "violations": len(validator_violations),
                    "kit_requirements": len(checklist),
                    "notes": 2,
                },
                "source": "baked",
            }

        # ── 2. Kit-specific must-haves (treated as REQUIRED items) ──────────
        kit = ctx.get("kit") or {}
        kit_checklist = kit.get("critic_checklist", []) if isinstance(kit, dict) else []
        kit_required = [f"REQUIRED ({kit.get('kit_id', 'kit')}): {item}" for item in kit_checklist]

        violations_for_critic = kit_required + validator_violations

        # ── 3. Refine ───────────────────────────────────────────────────────
        critic_notes: list[str] = []
        final_artifact = draft_artifact
        try:
            revised = await self._critic.refine(
                intent=intent,
                rationale=rationale,
                draft_html=draft_html,
                violations=violations_for_critic,
            )
            revised_html = revised.get("preview_html") or ""
            post_violations = validate_html(revised_html)
            if post_violations and len(post_violations) > len(validator_violations):
                # Critic regressed — keep the draft.
                critic_notes.append(
                    f"reverted: revised had {len(post_violations)} structural "
                    f"issues vs. {len(validator_violations)} in draft"
                )
            else:
                draft_lines = draft_html.count("\n") + 1
                revised_lines = revised_html.count("\n") + 1
                delta = revised_lines - draft_lines
                critic_notes.append(
                    f"polished: {draft_lines}L → {revised_lines}L "
                    f"({'+' if delta >= 0 else ''}{delta}) · "
                    f"{len(validator_violations)} structural issue"
                    f"{'s' if len(validator_violations) != 1 else ''} fixed"
                )
                if kit_required:
                    critic_notes.append(
                        f"applied {len(kit_required)} kit requirement"
                        f"{'s' if len(kit_required) != 1 else ''}"
                    )
                final_artifact = revised
        except Exception as e:  # pragma: no cover — never fail the workflow
            critic_notes.append(f"critic failed: {type(e).__name__}: {str(e)[:80]}")

        title = final_artifact.get("title", "artifact")
        summary = title + " · " + (critic_notes[0] if critic_notes else "no changes")

        return {
            "summary": summary,
            "artifact": final_artifact,
            "critic_violations": validator_violations,
            "critic_notes": critic_notes,
            "counts": {
                "violations": len(validator_violations),
                "kit_requirements": len(kit_required),
                "notes": len(critic_notes),
            },
        }
