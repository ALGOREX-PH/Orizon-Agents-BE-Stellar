from __future__ import annotations

import secrets

from ..agents.orchestrator import orchestrator_agent
from ..demo_kits import DemoKit, detect_kit
from ..schemas import DecomposeResponse, Plan, PlanStep, StoredPlan
from ..state import state


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
    "agt_09l5": 0.6,   # research (deterministic from kit)
    "agt_05x7": 0.5,   # seo brief (deterministic from kit)
    "agt_02k2": 0.4,   # design tokens (deterministic from kit)
    "agt_11c0": 2.6,   # code.gen (real LLM call — heaviest step)
    "agt_12r0": 1.8,   # code.critic (real LLM call)
    "agt_08j2": 0.4,   # deploy (deterministic seal)
}


def _registry_prompt_fragment() -> str:
    lines = ["AVAILABLE_AGENTS:"]
    for a in state.list_agents():
        lines.append(
            f"- id={a.id} name={a.name} price={a.price:.3f} rep={a.rep:.2f} "
            f"skills={','.join(a.skills)}"
        )
    return "\n".join(lines)


def _build_kit_plan(intent: str, kit: DemoKit) -> DecomposeResponse:
    """Deterministic 6-step plan for a curated demo intent. No LLM call."""
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
    state.plans[plan_id] = stored

    return DecomposeResponse(
        plan_id=plan_id,
        intent=intent,
        steps=steps,
        total_usdc=round(total_price, 4),
        total_eta=round(total_eta, 2),
    )


async def decompose(intent: str) -> DecomposeResponse:
    # ── Demo-kit short circuit ─────────────────────────────────────────────
    # If the intent matches a curated kit (tetris / calculator / snake /
    # pomodoro), bypass the LLM orchestrator entirely and return the
    # deterministic 6-step pipeline. Reliable for live demos; no LLM cost.
    kit = detect_kit(intent)
    if kit is not None:
        return _build_kit_plan(intent, kit)

    # ── Free-form path: LLM orchestrator decides the plan ──────────────────
    prompt = f"""{_registry_prompt_fragment()}

USER_INTENT: {intent}

Return the Plan."""
    result = await orchestrator_agent.arun(prompt)
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
    state.plans[plan_id] = stored

    return DecomposeResponse(
        plan_id=plan_id,
        intent=intent,
        steps=cleaned,
        total_usdc=round(total_price, 4),
        total_eta=round(total_eta, 2),
    )
