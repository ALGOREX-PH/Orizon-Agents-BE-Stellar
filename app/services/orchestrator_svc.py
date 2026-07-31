from __future__ import annotations

import asyncio
import logging
import random
import secrets
from typing import Any

from ..agents.orchestrator import orchestrator_agent
from ..agents.workers.prompt_safety import fence_user_input
from ..config import settings
from ..demo_kits import DemoKit, detect_kit
from ..schemas import DecomposeResponse, Plan, PlanStep, StoredPlan
from ..state import state
from . import reputation_svc

logger = logging.getLogger(__name__)

# The reputation floor may never starve the planner of choices.
_MIN_ROUTABLE_AGENTS = 3


# ── Curated 6-step pipeline used when the intent matches a DemoKit ─────────
# (agent_id, rationale-template). Prices come from the registry at build time.
_KIT_PIPELINE: list[tuple[str, str]] = [
    ("agt_09l5", "extract feature brief + edge cases for the build"),
    ("agt_05x7", "produce brand identity: name, tagline, audience"),
    ("agt_02k2", "lock design tokens: palette, typography, motion"),
    ("agt_11c0", "implement single-file HTML using brief + tokens"),
    ("agt_12r0", "polish pass: a11y, motion, persistence, edge cases"),
    ("agt_08j2", "seal artifact + record on-chain proof"),
]

# ETAs are rough but realistic per agent for a kit run.
_KIT_ETAS: dict[str, float] = {
    "agt_09l5": 0.6,  # research (deterministic from kit)
    "agt_05x7": 0.5,  # seo brief (deterministic from kit)
    "agt_02k2": 0.4,  # design tokens (deterministic from kit)
    "agt_11c0": 2.6,  # code.gen (real LLM call — heaviest step)
    "agt_12r0": 1.8,  # code.critic (real LLM call)
    "agt_08j2": 0.4,  # deploy (deterministic seal)
}


def _rep_fields(info: reputation_svc.RepInfo | None) -> dict[str, Any]:
    """PlanStep reputation stamp — empty when the agent has no rep entry."""
    if info is None:
        return {}
    return {"rep_bps": info.smoothed_bps, "rep_source": info.source}


def _registry_prompt_fragment(reps: dict[str, reputation_svc.RepInfo]) -> str:
    agents = state.list_agents()
    routable = [a for a in agents if reputation_svc.passes_floor(reps.get(a.id))]
    if len(routable) < _MIN_ROUTABLE_AGENTS:
        logger.warning(
            "reputation floor left only %d/%d agents routable; keeping top %d by smoothed score",
            len(routable),
            len(agents),
            _MIN_ROUTABLE_AGENTS,
        )
        routable = sorted(
            agents,
            key=lambda a: reps[a.id].smoothed_bps if a.id in reps else round(a.rep * 2000),
            reverse=True,
        )[:_MIN_ROUTABLE_AGENTS]

    lines = ["AVAILABLE_AGENTS:"]
    for a in routable:
        info = reps.get(a.id)
        # Live smoothed score on the 0–5 scale the prompt already uses;
        # seeded rep only when the agent has no reputation entry.
        rep_display = info.smoothed_bps / 2000 if info is not None else a.rep
        lines.append(f"- id={a.id} name={a.name} price={a.price:.3f} rep={rep_display:.2f} skills={','.join(a.skills)}")
    return "\n".join(lines)


def build_planning_prompt(registry_block: str, intent: str) -> str:
    """Registry facts, then the FENCED intent, then the ask.

    The intent is free-form and attacker-controllable, so it is never spliced
    bare next to AVAILABLE_AGENTS — it arrives as a delimited data block the
    planner is told not to obey. The trusted instruction goes last.
    """
    return "\n\n".join([registry_block, fence_user_input(intent), "Return the Plan."])


async def _build_kit_plan(intent: str, kit: DemoKit, reps: dict[str, reputation_svc.RepInfo]) -> DecomposeResponse:
    """Deterministic 6-step plan for a curated demo intent. No LLM call.

    A short randomized sleep up front mimics orchestrator "thinking time" so
    the Decompose UX feels like real LLM planning instead of a hardcoded dict
    being unpacked. ~1.4–2.4 s matches what a small reasoning-model call to
    plan 6 steps would actually take.
    """
    await asyncio.sleep(1.4 + random.random() * 1.0)

    steps: list[PlanStep] = []
    for agent_id, rationale in _KIT_PIPELINE:
        agent = state.agents.get(agent_id)
        if agent is None:
            # The kit pipeline references an agent that isn't seeded — this
            # is a programmer error. Skip the step rather than crash the
            # whole pipeline.
            continue
        steps.append(
            PlanStep(
                agent_id=agent.id,
                agent_name=agent.name,
                rationale=rationale,
                est_price_usdc=agent.price,
                est_eta_seconds=_KIT_ETAS.get(agent_id, 1.0),
                **_rep_fields(reps.get(agent.id)),
            )
        )

    plan_id = f"pln_{secrets.token_hex(4)}"
    total_price = sum(s.est_price_usdc for s in steps)
    total_eta = sum(s.est_eta_seconds for s in steps)

    stored = StoredPlan(
        id=plan_id,
        intent=intent,
        plan=Plan(steps=steps),
        total_usdc=total_price,
        total_eta=total_eta,
    )
    state.add_plan(stored)

    return DecomposeResponse(
        plan_id=plan_id,
        intent=intent,
        steps=steps,
        total_usdc=round(total_price, 4),
        total_eta=round(total_eta, 2),
    )


async def decompose(intent: str) -> DecomposeResponse:
    # One live reputation snapshot per decompose — timeout-bounded and never
    # raises (prior fallback), shared by the kit path, the routing prompt,
    # and the per-step reputation stamps.
    reps = await reputation_svc.fetch_reps([a.id for a in state.list_agents()])

    # ── Demo-kit short circuit ─────────────────────────────────────────────
    # If the intent matches a curated kit (tetris / calculator / snake /
    # pomodoro), bypass the LLM orchestrator entirely and return the
    # deterministic 6-step pipeline. Reliable for live demos; no LLM cost.
    kit = detect_kit(intent)
    if kit is not None:
        return await _build_kit_plan(intent, kit, reps)

    # ── Free-form path: LLM orchestrator decides the plan ──────────────────
    prompt = build_planning_prompt(_registry_prompt_fragment(reps), intent)
    # Hard end-to-end budget for the planning call — without it a hung
    # upstream would pin this request for the OpenAI client's full
    # timeout x retry envelope. The router maps TimeoutError to a 504.
    result = await asyncio.wait_for(
        orchestrator_agent.arun(prompt),
        timeout=settings.decompose_timeout_seconds,
    )
    plan: Plan = result.content  # type: ignore[assignment]

    # Clamp to known agents; backfill names + snap price to registry truth.
    cleaned: list[PlanStep] = []
    for step in plan.steps:
        agent = state.agents.get(step.agent_id)
        if not agent:
            # Drop unknown ids silently — the model sometimes invents.
            continue
        cleaned.append(
            PlanStep(
                agent_id=agent.id,
                agent_name=agent.name,
                rationale=step.rationale.strip(),
                est_price_usdc=agent.price,
                est_eta_seconds=max(0.3, min(step.est_eta_seconds, 3.0)),
                **_rep_fields(reps.get(agent.id)),
            )
        )

    if not cleaned:
        # Fall back to a minimal safe plan so the UI never gets stuck.
        copy_agent = state.agents["agt_01h8"]
        cleaned = [
            PlanStep(
                agent_id=copy_agent.id,
                agent_name=copy_agent.name,
                rationale="fallback: generate copy for the intent",
                est_price_usdc=copy_agent.price,
                est_eta_seconds=0.8,
                **_rep_fields(reps.get(copy_agent.id)),
            )
        ]

    plan_id = f"pln_{secrets.token_hex(4)}"
    total_price = sum(s.est_price_usdc for s in cleaned)
    total_eta = sum(s.est_eta_seconds for s in cleaned)

    stored = StoredPlan(
        id=plan_id,
        intent=intent,
        plan=Plan(steps=cleaned),
        total_usdc=total_price,
        total_eta=total_eta,
    )
    state.add_plan(stored)

    return DecomposeResponse(
        plan_id=plan_id,
        intent=intent,
        steps=cleaned,
        total_usdc=round(total_price, 4),
        total_eta=round(total_eta, 2),
    )
